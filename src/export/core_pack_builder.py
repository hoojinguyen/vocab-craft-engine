"""
Core 3000 Word Pack Builder.

Reads the full pipeline database (data/output/english_dataset.db), selects the
~3,000 most common English words (validated by NGSL overlap + Tatoeba corpus
coverage), enriches each word with quality-gated fields, and exports an
app-focused core_3000.db plus quality_report.md.
"""

import csv
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from config.settings import NGSL_PATH
from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)

_VI_VALIDATOR = VietnameseTextValidator()

# Frequency-form -> lemma normalizations (SUBTL-form: lowercase, apostrophes removed)
CONTRACTION_MAP = {
    "dont": "do", "don": "do", "doesnt": "do", "didnt": "do", "doin": "do",
    "cant": "can", "couldnt": "could", "wouldnt": "would", "shouldnt": "should",
    "wont": "will", "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "im": "i", "ive": "i", "id": "i", "ill": "i", "id": "i",
    "youre": "you", "youve": "you", "youd": "you", "youll": "you",
    "theyre": "they", "theyve": "they", "theyd": "they", "theyll": "they",
    "hes": "he", "shes": "she", "weve": "we", "well": "will",
    "thats": "that", "theres": "there", "havent": "have", "hasnt": "have",
}

NOISE_POS = {"name", "prefix", "suffix", "symbol", "particle", "num", "punct"}

# Pack CEFR thresholds (spec section 4.1)
CEFR_RANK_THRESHOLDS = [("A1", 500), ("A2", 1500), ("B1", 3500), ("B2", 7000), ("C1", 15000)]


def normalize_freq_word(word: str) -> str:
    """Lowercases, strips punctuation/quotes, expands contractions to lemmas."""
    w = (word or "").strip().lower().strip("'\"`-")
    w = w.replace("'", "")
    return CONTRACTION_MAP.get(w, w)


def rank_to_cefr(rank: int) -> str:
    """Maps a frequency rank to a pack CEFR level (spec section 4.1)."""
    for level, threshold in CEFR_RANK_THRESHOLDS:
        if rank <= threshold:
            return level
    return "C2"


def select_core_words(
    conn: sqlite3.Connection,
    freq_ranks: Dict[str, int],
    target: int = 3000,
    window: int = 3500,
) -> List[Dict[str, Any]]:
    """
    Selects up to `target` words in frequency order from the words table.

    Iterates the frequency file in rank order, normalizes each form,
    joins against the words table, filters noise POS, dedupes by lemma,
    and stops at `target` or when the rank window is exhausted.
    """
    selected: List[Dict[str, Any]] = []
    seen_lemmas: Set[str] = set()

    for raw_word, rank in sorted(freq_ranks.items(), key=lambda kv: kv[1]):
        if rank > window:
            break
        lemma = normalize_freq_word(raw_word)
        if not lemma or lemma in seen_lemmas:
            continue
        row = conn.execute(
            "SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level "
            "FROM words WHERE lemma = ?",
            (lemma,),
        ).fetchone()
        if row is None:
            continue
        if row[2] in NOISE_POS:
            continue
        seen_lemmas.add(lemma)
        selected.append({
            "id": row[0], "lemma": row[1], "pos": row[2],
            "ipa_uk": row[3], "ipa_us": row[4],
            "frequency_rank": row[5], "cefr_level": row[6],
        })
        if len(selected) >= target:
            break

    return selected


def load_ngsl(path: Path) -> Set[str]:
    """Loads NGSL headwords (first CSV column) into a set."""
    if not Path(path).exists():
        return set()
    words: Set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")
            if parts and parts[0].strip():
                words.add(parts[0].strip().lower())
    return words


def ngsl_overlap(lemmas: List[str], ngsl_words: Set[str]) -> float:
    """Fraction of the pack lemmas present in the NGSL list."""
    if not lemmas:
        return 0.0
    return len(set(lemmas) & ngsl_words) / len(lemmas)


def tatoeba_coverage(conn: sqlite3.Connection, lemmas: Set[str]) -> float:
    """
    Fraction of Tatoeba tokens whose normalized lemma is in the pack set.
    Tokens are lowercased, punctuation-stripped, and contraction-normalized.
    """
    rows = conn.execute("SELECT text_en FROM sentences").fetchall()
    total_tokens = 0
    covered_tokens = 0
    for (text_en,) in rows:
        for token in text_en.split():
            total_tokens += 1
            normalized = normalize_freq_word(token.strip(".,!?;:\"'()[]"))
            if normalized in lemmas:
                covered_tokens += 1
    return covered_tokens / total_tokens if total_tokens else 0.0


def select_core_words_with_gates(
    conn: sqlite3.Connection,
    freq_dict: Dict[str, int],
    ngsl_path: Path = NGSL_PATH,
    target: int = 3000,
    min_overlap: float = 0.85,
    min_coverage: float = 0.90,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Selects core words, widening the rank window (3500 -> 5000) until the
    NGSL overlap and Tatoeba coverage gates pass. Returns (selected, metrics).
    """
    ngsl_words = load_ngsl(ngsl_path)
    best_selected: List[Dict[str, Any]] = []
    best_metrics: Dict[str, Any] = {}

    for window in (3500, 4000, 4500, 5000):
        selected = select_core_words(conn, freq_dict, target=target, window=window)
        lemmas = [w["lemma"] for w in selected]
        overlap = ngsl_overlap(lemmas, ngsl_words)
        coverage = tatoeba_coverage(conn, set(lemmas))
        metrics = {
            "window": window,
            "selected": len(selected),
            "ngsl_overlap": round(overlap, 4),
            "tatoeba_coverage": round(coverage, 4),
            "passed": overlap >= min_overlap and coverage >= min_coverage,
        }
        logger.info("Core selection window=%s -> overlap=%.1f%% coverage=%.1f%%",
                    window, overlap * 100, coverage * 100)
        best_selected, best_metrics = selected, metrics
        if metrics["passed"]:
            break

    return best_selected, best_metrics


LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
GATES = ("definition", "definition_vi", "example_en", "example_vi", "ipa", "topic", "audio", "cefr")


class CorePackBuilder:
    """
    Selects, enriches, and exports the core word pack.

    Selection enforces NGSL overlap + Tatoeba coverage gates; enrichment
    quality-gates each word and quarantines failures; build() exports the
    pack database (core_3000.db with indexes, quarantine, collocations and
    phrases rooted in the pack) plus quality_report.md.

    source_db_path: the full pipeline database (english_dataset.db).
    output_dir: directory for the pack (core_3000.db + audio/ + quality_report.md).
    """

    _AUDIO_CHUNK = 20

    def __init__(self, source_db_path: Path, output_dir: Path):
        self.source_db_path = Path(source_db_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir = self.output_dir / "audio"
        self.db_path = self.output_dir / "core_3000.db"
        self._audio_gen_instance = None
        self._cp = self._load_checkpoint()

    # ---- checkpoint ----------------------------------------------------

    @property
    def checkpoint_path(self) -> Path:
        return self.output_dir / "checkpoint.json"

    def _load_checkpoint(self) -> Dict[str, Any]:
        if self.checkpoint_path.exists():
            try:
                return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Failed to parse checkpoint %s; starting fresh", self.checkpoint_path)
                return {"done": {}}
        return {"done": {}}

    def _save_checkpoint(self, checkpoint: Dict[str, Any]):
        tmp = self.checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.checkpoint_path)

    def _is_done(self, word_id: int) -> bool:
        return str(word_id) in self._cp.get("done", {})

    # ---- audio ---------------------------------------------------------

    @property
    def _audio_gen(self):
        from src.media.audio_generator import AudioGenerator
        if self._audio_gen_instance is None:
            self._audio_gen_instance = AudioGenerator(output_dir=self.audio_dir)
        return self._audio_gen_instance

    async def _generate_word_audio(self, word_id: int, lemma: str) -> Tuple[Optional[str], Optional[str]]:
        audio_gen = self._audio_gen
        results = await audio_gen.generate_dual_speed_word(word_id, lemma)
        std = results["standard_path"]
        fast = results["fast_path"]
        if std is None or fast is None:
            return None, None
        return f"audio/std/w_{word_id}_std.mp3", f"audio/fast/w_{word_id}_fast.mp3"

    # ---- topic lookup -------------------------------------------------

    def _topics_by_word(self, conn: sqlite3.Connection) -> Dict[int, List[str]]:
        """Maps word_id -> mapped themes (raw topics collapsed via TopicMapper)."""
        from src.nlp.topic_mapper import TopicMapper
        topics: Dict[int, List[str]] = {}
        rows = conn.execute(
            "SELECT word_id, raw_topic FROM word_topics ORDER BY word_id, topic"
        ).fetchall()
        for word_id, raw_topic in rows:
            theme = TopicMapper.map_topic(raw_topic)
            if theme not in topics.setdefault(word_id, []):
                topics[word_id].append(theme)
        return topics

    def _definitions_by_word(self, conn: sqlite3.Connection) -> Dict[int, Tuple[Any, ...]]:
        """Maps word_id -> first definition row (definition_en, definition_vi, example) in one pass."""
        first: Dict[int, Tuple[Any, ...]] = {}
        for word_id, def_en, def_vi, example in conn.execute(
            "SELECT word_id, definition_en, definition_vi, example "
            "FROM definitions ORDER BY word_id, id"
        ):
            if word_id not in first:
                first[word_id] = (def_en, def_vi, example)
        return first

    # ---- enrichment ---------------------------------------------------

    def _enrich_word(
        self,
        conn: sqlite3.Connection,
        word_row: Tuple[Any, ...],
        translator: Any,
        topics_by_word: Optional[Dict[int, List[str]]] = None,
        definitions_by_word: Optional[Dict[int, Tuple[Any, ...]]] = None,
    ) -> Dict[str, Any]:
        """
        Enriches a single word row. On gate failure returns a result dict
        with 'quarantine' set to the failing gate name.
        """
        word_id, lemma, pos, ipa_uk, ipa_us, freq_rank, _old_cefr = word_row[:7]
        validator = _VI_VALIDATOR

        # definition (first sense)
        if definitions_by_word is not None:
            def_row = definitions_by_word.get(word_id)
        else:
            def_row = conn.execute(
                "SELECT definition_en, definition_vi, example FROM definitions "
                "WHERE word_id = ? ORDER BY id LIMIT 1",
                (word_id,),
            ).fetchone()
        if def_row is None:
            return {"word": None, "quarantine": "definition"}
        definition_en, existing_vi, kaikki_example = def_row

        # definition_vi
        definition_vi = ""
        if existing_vi and validator.is_vietnamese(existing_vi):
            definition_vi = existing_vi
        else:
            definition_vi = translator.translate_text(definition_en)
        if not validator.is_vietnamese(definition_vi):
            return {"word": None, "quarantine": "definition_vi"}

        # example (Tatoeba preferred, Kaikki fallback)
        topics = (topics_by_word or {}).get(word_id, [])
        cefr = rank_to_cefr(freq_rank)
        max_level = LEVEL_ORDER[min(LEVEL_ORDER.index(cefr) + 1, len(LEVEL_ORDER) - 1)]
        sent_row = conn.execute(
            "SELECT s.text_en, s.text_vi FROM word_sentence_map wsm "
            "JOIN sentences s ON s.id = wsm.sentence_id "
            "WHERE wsm.word_id = ? AND s.cefr_level <= ? AND s.text_vi IS NOT NULL "
            "ORDER BY s.difficulty_score LIMIT 1",
            (word_id, max_level),
        ).fetchone()
        if sent_row is not None:
            example_en, example_vi = sent_row
        elif kaikki_example:
            example_en = kaikki_example
            example_vi = translator.translate_text(kaikki_example)
        else:
            return {"word": None, "quarantine": "example_en"}
        if not example_en or not example_vi:
            return {"word": None, "quarantine": "example_vi"}

        # ipa
        if not ipa_uk and not ipa_us:
            return {"word": None, "quarantine": "ipa"}

        # topic (General & Everyday fallback never gates; a real theme beats it)
        topic = next((t for t in topics if t != "General & Everyday"), "General & Everyday")

        return {
            "word": {"id": word_id, "lemma": lemma, "pos": pos},
            "cefr_level": cefr,
            "frequency_rank": freq_rank,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "definition_en": definition_en,
            "definition_vi": definition_vi,
            "example_en": example_en,
            "example_vi": example_vi,
            "topic": topic,
            "quarantine": None,
        }

    # ---- export -------------------------------------------------------

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY,
        lemma TEXT NOT NULL,
        pos TEXT,
        cefr_level TEXT,
        frequency_rank INTEGER,
        ipa_uk TEXT,
        ipa_us TEXT,
        audio_std TEXT,
        audio_fast TEXT,
        audio_status TEXT
    );
    CREATE TABLE IF NOT EXISTS word_topics (
        word_id INTEGER,
        topic TEXT
    );
    CREATE TABLE IF NOT EXISTS definitions (
        id INTEGER PRIMARY KEY,
        word_id INTEGER,
        definition_en TEXT,
        definition_vi TEXT,
        example_en TEXT,
        example_vi TEXT,
        example_vi_source TEXT
    );
    CREATE TABLE IF NOT EXISTS sentences (
        id INTEGER PRIMARY KEY,
        text_en TEXT,
        text_vi TEXT,
        cefr_level TEXT,
        audio_path TEXT,
        source TEXT
    );
    CREATE TABLE IF NOT EXISTS word_sentences (
        word_id INTEGER,
        sentence_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS collocations (
        id INTEGER PRIMARY KEY,
        phrase TEXT,
        meaning_vi TEXT,
        pos_pattern TEXT,
        cefr_level TEXT,
        root_word_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS phrases (
        id INTEGER PRIMARY KEY,
        phrase TEXT,
        definition_en TEXT,
        definition_vi TEXT,
        cefr_level TEXT,
        audio_std TEXT,
        audio_fast TEXT
    );
    CREATE TABLE IF NOT EXISTS quarantine (
        word_id INTEGER,
        lemma TEXT,
        failed_gate TEXT
    );
    """

    def _init_pack_db(self) -> sqlite3.Connection:
        if self.db_path.exists():
            self.db_path.unlink()
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(self.SCHEMA)
        return conn

    def build(
        self,
        freq_dict: Dict[str, int],
        ngsl_path: Path = NGSL_PATH,
        target: int = 3000,
        vi_budget: int = 5000,
    ) -> Dict[str, Any]:
        """
        Runs selection -> enrichment -> audio -> export for the pack.
        Returns a metrics report dict.
        """
        import asyncio
        from src.nlp.translator import Translator

        source = sqlite3.connect(str(self.source_db_path))
        selected, metrics = select_core_words_with_gates(
            source, freq_dict, ngsl_path=ngsl_path, target=target
        )
        topics_by_word = self._topics_by_word(source)
        definitions_by_word = self._definitions_by_word(source)

        translator = Translator()
        pack_conn = self._init_pack_db()
        sent_id_map: Dict[str, int] = {}
        next_sent_id = 1

        enriched = []
        quarantined = []
        pending = []
        for word in selected:
            if self._is_done(word["id"]):
                continue
            result = self._enrich_word(source, (
                word["id"], word["lemma"], word["pos"], word["ipa_uk"],
                word["ipa_us"], word["frequency_rank"], word["cefr_level"],
            ), translator, topics_by_word, definitions_by_word)
            if result["quarantine"]:
                quarantined.append({"word_id": word["id"], "lemma": word["lemma"],
                                    "failed_gate": result["quarantine"]})
                continue
            pending.append((word, result))

        # generate audio in parallel chunks
        chunk = 0
        while chunk < len(pending):
            batch = pending[chunk:chunk + self._AUDIO_CHUNK]
            async def _run_batch(batch_items):
                coros = [self._generate_word_audio(word["id"], word["lemma"])
                         for word, _ in batch_items]
                return await asyncio.gather(*coros)
            audio_results = asyncio.run(_run_batch(batch))
            for (word, result), (std_path, fast_path) in zip(batch, audio_results):
                if std_path is None or fast_path is None:
                    quarantined.append({"word_id": word["id"], "lemma": word["lemma"],
                                        "failed_gate": "audio"})
                    continue
                result["audio_std"] = std_path
                result["audio_fast"] = fast_path
                enriched.append(result)
                self._cp["done"][str(word["id"])] = True
            if enriched:
                self._save_checkpoint(self._cp)
            chunk += self._AUDIO_CHUNK

        # -- write words + definitions + topics --------------------------
        for r in enriched:
            pack_conn.execute(
                "INSERT INTO words (id, lemma, pos, cefr_level, frequency_rank, "
                "ipa_uk, ipa_us, audio_std, audio_fast, audio_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')",
                (r["word"]["id"], r["word"]["lemma"], r["word"]["pos"], r["cefr_level"],
                 r["frequency_rank"], r["ipa_uk"], r["ipa_us"],
                 r["audio_std"], r["audio_fast"]),
            )
            pack_conn.execute(
                "INSERT INTO word_topics (word_id, topic) VALUES (?, ?)",
                (r["word"]["id"], r["topic"]),
            )
            pack_conn.execute(
                "INSERT INTO definitions (word_id, definition_en, definition_vi, "
                "example_en, example_vi, example_vi_source) VALUES (?, ?, ?, ?, ?, 'validated')",
                (r["word"]["id"], r["definition_en"], r["definition_vi"],
                 r["example_en"], r["example_vi"]),
            )
            pack_conn.execute(
                "INSERT INTO sentences (id, text_en, text_vi, cefr_level, source) "
                "VALUES (?, ?, ?, ?, 'Tatoeba')",
                (next_sent_id, r["example_en"], r["example_vi"], r["cefr_level"]),
            )
            pack_conn.execute(
                "INSERT INTO word_sentences (word_id, sentence_id) VALUES (?, ?)",
                (r["word"]["id"], next_sent_id),
            )
            sent_id_map[r["word"]["id"]] = next_sent_id
            next_sent_id += 1

        # -- collocations & phrases rooted in the pack --------------------
        core_lemma_ids = {r["word"]["id"] for r in enriched}
        first_words = {w["lemma"]: w["id"] for w in selected}
        colloc_rows = source.execute(
            "SELECT c.phrase, c.meaning_vi, c.pos_pattern, c.cefr_level, c.id "
            "FROM collocations c"
        ).fetchall()
        pack_collocs = 0
        for phrase, meaning_vi, pos_pattern, cefr_level, colloc_id in colloc_rows:
            first = phrase.split()[0].strip().lower() if phrase else ""
            root_id = first_words.get(first)
            if root_id in core_lemma_ids:
                pack_conn.execute(
                    "INSERT INTO collocations (phrase, meaning_vi, pos_pattern, "
                    "cefr_level, root_word_id) VALUES (?, ?, ?, ?, ?)",
                    (phrase, meaning_vi, pos_pattern, cefr_level, root_id),
                )
                pack_collocs += 1

        phrase_rows = source.execute(
            "SELECT phrase, definition_en, definition_vi, cefr_level, audio_std, audio_fast "
            "FROM phrases WHERE cefr_level IN ('A1','A2','B1','B2')"
        ).fetchall()
        pack_phrases = 0
        for phrase, def_en, def_vi, cefr_level, audio_std, audio_fast in phrase_rows:
            first = phrase.split()[0].strip().lower() if phrase else ""
            if first in first_words:
                pack_conn.execute(
                    "INSERT INTO phrases (phrase, definition_en, definition_vi, "
                    "cefr_level, audio_std, audio_fast) VALUES (?, ?, ?, ?, ?, ?)",
                    (phrase, def_en, def_vi, cefr_level, audio_std, audio_fast),
                )
                pack_phrases += 1

        for q in quarantined:
            pack_conn.execute(
                "INSERT INTO quarantine (word_id, lemma, failed_gate) VALUES (?, ?, ?)",
                (q["word_id"], q["lemma"], q["failed_gate"]),
            )

        # -- indexes + WAL + vacuum ---------------------------------------
        pack_conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_pack_defs_word ON definitions(word_id);
            CREATE INDEX IF NOT EXISTS idx_pack_topics_word ON word_topics(word_id);
            CREATE INDEX IF NOT EXISTS idx_pack_topics_topic ON word_topics(topic);
            CREATE INDEX IF NOT EXISTS idx_pack_ws_word ON word_sentences(word_id);
            CREATE INDEX IF NOT EXISTS idx_pack_ws_sent ON word_sentences(sentence_id);
            CREATE INDEX IF NOT EXISTS idx_pack_colloc_root ON collocations(root_word_id);
            CREATE INDEX IF NOT EXISTS idx_pack_phrases_cefr ON phrases(cefr_level);
            """
        )
        pack_conn.execute("PRAGMA journal_mode = WAL;")
        pack_conn.commit()
        pack_conn.execute("VACUUM;")
        pack_conn.close()

        self._save_checkpoint(self._cp)
        report = self._write_report(metrics, enriched, quarantined, pack_collocs, pack_phrases)
        source.close()
        return report

    def _write_report(
        self,
        metrics: Dict[str, Any],
        enriched: List[Dict[str, Any]],
        quarantined: List[Dict[str, Any]],
        colloc_count: int,
        phrase_count: int,
    ) -> Dict[str, Any]:
        total = len(enriched) + len(quarantined)
        pass_rate = len(enriched) / total if total else 0.0
        theme_counts: Dict[str, int] = {}
        cefr_counts: Dict[str, int] = {}
        for r in enriched:
            theme_counts[r["topic"]] = theme_counts.get(r["topic"], 0) + 1
            cefr_counts[r["cefr_level"]] = cefr_counts.get(r["cefr_level"], 0) + 1

        lines = [
            "# Core 3000 Pack Quality Report",
            "",
            f"- Selected: {metrics.get('selected', 0)}",
            f"- Window: {metrics.get('window')}",
            f"- NGSL overlap: {metrics.get('ngsl_overlap', 0) * 100:.1f}% (gate >= 85%)",
            f"- Tatoeba coverage: {metrics.get('tatoeba_coverage', 0) * 100:.1f}% (gate >= 90%)",
            f"- Pass rate: {pass_rate * 100:.1f}% (gate >= 97%)",
            f"- Quarantined: {len(quarantined)}",
            f"- Themes covered: {len(theme_counts)}/18",
            f"- Collocations linked: {colloc_count}",
            f"- Idioms linked: {phrase_count}",
            "",
            "## CEFR distribution",
            "",
            "| Level | Words |",
            "|-------|-------|",
        ]
        for level in LEVEL_ORDER:
            lines.append(f"| {level} | {cefr_counts.get(level, 0)} |")
        lines += ["", "## Theme distribution", "", "| Theme | Words |", "|-------|-------|"]
        for theme, count in sorted(theme_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {theme} | {count} |")
        lines += ["", "## Quarantined words", ""]
        if quarantined:
            lines.append("| lemma | gate |")
            lines.append("|-------|------|")
            for q in quarantined:
                lines.append(f"| {q['lemma']} | {q['failed_gate']} |")
        else:
            lines.append("None.")

        (self.output_dir / "quality_report.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )

        return {
            "selected": metrics.get("selected", 0),
            "pass_rate": round(pass_rate, 4),
            "quarantined": len(quarantined),
            "themes_covered": len(theme_counts),
            "collocations": colloc_count,
            "phrases": phrase_count,
        }


def build_report_invariants(pack_db_path: Path, report: Dict[str, Any]) -> List[str]:
    """Validates pack invariants; returns a list of violation strings (empty = healthy)."""
    violations: List[str] = []
    conn = sqlite3.connect(str(pack_db_path))
    word_count = conn.execute("SELECT count(*) FROM words").fetchone()[0]
    if word_count != report["selected"] - report["quarantined"]:
        violations.append(f"word count {word_count} != selected - quarantined")
    no_topic = conn.execute(
        "SELECT count(*) FROM words w WHERE NOT EXISTS "
        "(SELECT 1 FROM word_topics t WHERE t.word_id = w.id)"
    ).fetchone()[0]
    if no_topic:
        violations.append(f"{no_topic} words without a topic")
    relative = conn.execute(
        "SELECT count(*) FROM words WHERE audio_std IS NOT NULL AND "
        "(audio_std LIKE '/%' OR audio_fast LIKE '/%')"
    ).fetchone()[0]
    if relative:
        violations.append("absolute audio paths found")
    missing_vi = conn.execute(
        "SELECT count(*) FROM definitions WHERE definition_vi IS NULL OR "
        "example_vi IS NULL"
    ).fetchone()[0]
    if missing_vi:
        violations.append(f"{missing_vi} definitions missing Vietnamese")
    conn.close()
    return violations

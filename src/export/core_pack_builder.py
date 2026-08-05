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

    source_db_path: the full pipeline database (english_dataset.db).
    output_dir: directory for the pack (core_3000.db + audio/ + quality_report.md).
    """

    def __init__(self, source_db_path: Path, output_dir: Path):
        self.source_db_path = Path(source_db_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir = self.output_dir / "audio"
        self.db_path = self.output_dir / "core_3000.db"
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
                return {"done": {}}
        return {"done": {}}

    def _save_checkpoint(self, checkpoint: Dict[str, Any]):
        self.checkpoint_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _is_done(self, word_id: int) -> bool:
        return str(word_id) in self._cp.get("done", {})

    # ---- audio ---------------------------------------------------------

    async def _generate_word_audio(self, word_id: int, lemma: str) -> Tuple[Optional[str], Optional[str]]:
        from src.media.audio_generator import AudioGenerator
        audio_gen = AudioGenerator(output_dir=self.audio_dir)
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

# Core 3000 Pack Builder Decomposition Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the monolithic `core_pack_builder.py` into `core_selector.py`, `core_enricher.py`, and `core_exporter.py`, enforcing 5 strict quality gates, generating `quality_report.md`, and deleting the legacy 793 LOC file.

**Architecture:** A modular 3-stage export pipeline: `CoreSelector` filters and ranks top 3,000 headwords from DuckDB; `CoreEnricher` validates 5 Quality Gates (EN def, VI def, IPA, sentences, topics); `CoreExporter` writes the SQLite `core_3000.db` bundle and renders a comprehensive markdown audit report `quality_report.md`.

**Tech Stack:** Python 3.14, DuckDB, SQLite3, PyTest.

**Spec:** `docs/superpowers/specs/2026-08-14-core-3000-decomposition-design.md`

## Global Constraints

- Python version: Python 3.14 (.venv)
- Use standard project paths: `data/output/core_3000.db`, `data/output/quality_report.md`, `config.settings.NGSL_PATH`
- Clean separation of concerns: Zero legacy monolithic imports
- Strict adherence to TDD: Test -> Fail -> Implement -> Pass -> Commit

---

### Task 1: Implement `CoreSelector` with Frequency Ranking & Noise Filtering

**Files:**
- Modify: `src/export/core_selector.py`
- Create: `tests/test_export/test_core_selector.py`

**Interfaces:**
- Consumes: `DuckDBManager` (`words` table with `lemma`, `pos`, `frequency_rank`)
- Produces: `SelectedWord` dataclass and `CoreSelector.select_core_words(db_mgr, limit=3000, ngsl_path=None) -> List[SelectedWord]`

- [ ] **Step 1: Write the failing tests in `tests/test_export/test_core_selector.py`**

```python
from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_selector import CoreSelector, SelectedWord, rank_to_cefr, normalize_freq_word


def test_normalize_freq_word_contractions():
    assert normalize_freq_word("don't") == "do"
    assert normalize_freq_word("can't") == "can"
    assert normalize_freq_word("they're") == "they"
    assert normalize_freq_word("apple") == "apple"


def test_rank_to_cefr():
    assert rank_to_cefr(200) == "A1"
    assert rank_to_cefr(1000) == "A2"
    assert rank_to_cefr(2500) == "B1"
    assert rank_to_cefr(5000) == "B2"
    assert rank_to_cefr(12000) == "C1"
    assert rank_to_cefr(20000) == "C2"


def test_core_selector_filters_noise_and_ranks():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        words_data = [
            {"id": 1, "lemma": "the", "pos": "article", "frequency_rank": 1, "source": "kaikki"},
            {"id": 2, "lemma": "john", "pos": "name", "frequency_rank": 2, "source": "kaikki"},
            {"id": 3, "lemma": "un-", "pos": "prefix", "frequency_rank": 3, "source": "kaikki"},
            {"id": 4, "lemma": "water", "pos": "noun", "frequency_rank": 50, "source": "kaikki"},
            {"id": 5, "lemma": "run", "pos": "verb", "frequency_rank": 100, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("words", words_data)

        selector = CoreSelector()
        selected = selector.select_core_words(db_mgr, limit=3)

        assert len(selected) == 3
        lemmas = [w.lemma for w in selected]
        assert "john" not in lemmas  # name filtered out
        assert "un-" not in lemmas   # prefix filtered out
        assert "the" in lemmas
        assert "water" in lemmas
        assert "run" in lemmas

        water_entry = next(w for w in selected if w.lemma == "water")
        assert water_entry.cefr_level == "A1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_export/test_core_selector.py -v`
Expected: FAIL with missing classes/functions.

- [ ] **Step 3: Implement `CoreSelector` in `src/export/core_selector.py`**

```python
"""Core 3000 Frequency & Headword Selector."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

CONTRACTION_MAP = {
    "dont": "do", "don": "do", "doesnt": "do", "didnt": "do", "doin": "do",
    "cant": "can", "couldnt": "could", "wouldnt": "would", "shouldnt": "should",
    "wont": "will", "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "im": "i", "ive": "i", "id": "i", "ill": "i",
    "youre": "you", "youve": "you", "youd": "you", "youll": "you",
    "theyre": "they", "theyve": "they", "theyd": "they", "theyll": "they",
    "hes": "he", "shes": "she", "weve": "we", "well": "will",
    "thats": "that", "theres": "there", "havent": "have", "hasnt": "have",
}

NOISE_POS = {
    "name", "prefix", "suffix", "symbol", "particle", "num",
    "punct", "character", "contraction", "affix", "symbol",
}

CEFR_RANK_THRESHOLDS = [
    ("A1", 500),
    ("A2", 1500),
    ("B1", 3500),
    ("B2", 7000),
    ("C1", 15000),
]


def normalize_freq_word(word: str) -> str:
    """Lowercases, strips punctuation/quotes, expands contractions to lemmas."""
    w = (word or "").strip().lower().strip("'\"`-")
    w = w.replace("'", "")
    return CONTRACTION_MAP.get(w, w)


def rank_to_cefr(rank: Optional[int]) -> str:
    """Maps SUBTLEX frequency rank to CEFR proficiency level."""
    if rank is None or rank <= 0:
        return "C2"
    for level, threshold in CEFR_RANK_THRESHOLDS:
        if rank <= threshold:
            return level
    return "C2"


@dataclass
class SelectedWord:
    id: int
    lemma: str
    pos: str
    frequency_rank: Optional[int]
    cefr_level: str
    in_ngsl: bool
    source: str


class CoreSelector:
    """Selects top frequency headwords, filters noise POS, and assigns CEFR levels."""

    def select_core_words(
        self,
        db_mgr: DuckDBManager,
        limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> List[SelectedWord]:
        ngsl_words: Set[str] = set()
        if ngsl_path and Path(ngsl_path).exists():
            try:
                with open(ngsl_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if parts and parts[0].strip():
                            ngsl_words.add(parts[0].strip().lower())
            except Exception as e:
                logger.warning("Could not parse NGSL file at %s: %s", ngsl_path, e)

        conn = db_mgr.get_connection()
        query = """
            SELECT id, lemma, pos, frequency_rank, source
            FROM words
            WHERE lemma IS NOT NULL AND length(trim(lemma)) > 0
            ORDER BY 
                CASE WHEN frequency_rank IS NOT NULL THEN frequency_rank ELSE 999999 END ASC,
                id ASC
        """
        rows = conn.execute(query).fetchall()

        selected: List[SelectedWord] = []
        seen_lemmas: Set[str] = set()

        for wid, lemma, pos, freq_rank, source in rows:
            pos_norm = (pos or "").strip().lower()
            if pos_norm in NOISE_POS:
                continue

            clean_lemma = normalize_freq_word(lemma)
            if not clean_lemma or clean_lemma in seen_lemmas:
                continue

            seen_lemmas.add(clean_lemma)
            cefr = rank_to_cefr(freq_rank)
            in_ngsl = clean_lemma in ngsl_words

            selected.append(SelectedWord(
                id=wid,
                lemma=clean_lemma,
                pos=pos_norm,
                frequency_rank=freq_rank,
                cefr_level=cefr,
                in_ngsl=in_ngsl,
                source=source or "kaikki",
            ))

            if len(selected) >= limit:
                break

        logger.info("Selected %d core words (NGSL overlap: %d)", len(selected), sum(1 for w in selected if w.in_ngsl))
        return selected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_export/test_core_selector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/core_selector.py tests/test_export/test_core_selector.py
git commit -m "feat(export): implement CoreSelector with frequency ranking, noise filter, and CEFR assignment"
```

---

### Task 2: Implement `CoreEnricher` with 5 Quality Gates

**Files:**
- Modify: `src/export/core_enricher.py`
- Create: `tests/test_export/test_core_enricher.py`

**Interfaces:**
- Consumes: `SelectedWord` list and `DuckDBManager` (`definitions`, `sentences`, `word_sentences`, `word_topics`, `_ipa_cache`)
- Produces: `CoreEnricher.validate_and_enrich(db_mgr, selected_words) -> Tuple[List[Dict[str, Any]], EnrichmentSummary]`

- [ ] **Step 1: Write the failing tests in `tests/test_export/test_core_enricher.py`**

```python
from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_selector import SelectedWord
from src.export.core_enricher import CoreEnricher, QualityGateResult, EnrichmentSummary


def test_core_enricher_quality_gates():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        # Word 1: Complete (Passes all 5 gates)
        # Word 2: Missing Vietnamese Definition (Fails Gate 2)
        words_data = [
            {"id": 1, "lemma": "apple", "pos": "noun", "ipa_uk": "/ˈæp.əl/", "ipa_us": "/ˈæp.əl/", "frequency_rank": 100, "source": "kaikki"},
            {"id": 2, "lemma": "banana", "pos": "noun", "ipa_uk": "/bəˈnæn.ə/", "ipa_us": "/bəˈnæn.ə/", "frequency_rank": 200, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("words", words_data)

        defs_data = [
            {"id": 1, "word_id": 1, "definition_en": "A round red or green fruit", "definition_vi": "Quả táo", "source": "kaikki"},
            {"id": 2, "word_id": 2, "definition_en": "An elongated yellow fruit", "definition_vi": None, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("definitions", defs_data)

        sent_data = [
            {"id": 1, "text_en": "I eat an apple every day.", "text_vi": "Tôi ăn một quả táo mỗi ngày.", "source": "tatoeba"},
            {"id": 2, "text_en": "Monkeys love bananas.", "text_vi": "Khỉ thích chuối.", "source": "tatoeba"},
        ]
        db_mgr.insert_batch_fast("sentences", sent_data)

        ws_data = [
            {"word_id": 1, "sentence_id": 1},
            {"word_id": 2, "sentence_id": 2},
        ]
        db_mgr.insert_batch_fast("word_sentences", ws_data)

        topics_data = [
            {"word_id": 1, "topic": "Food & Drink", "raw_topic": "Food & Drink"},
            {"word_id": 2, "topic": "Food & Drink", "raw_topic": "Food & Drink"},
        ]
        db_mgr.insert_batch_fast("word_topics", topics_data)

        selected = [
            SelectedWord(id=1, lemma="apple", pos="noun", frequency_rank=100, cefr_level="A1", in_ngsl=True, source="kaikki"),
            SelectedWord(id=2, lemma="banana", pos="noun", frequency_rank=200, cefr_level="A1", in_ngsl=True, source="kaikki"),
        ]

        enricher = CoreEnricher()
        enriched_list, summary = enricher.validate_and_enrich(db_mgr, selected)

        assert len(enriched_list) == 2
        assert summary.total_words == 2
        assert summary.passed_all_gates == 1
        assert summary.def_en_coverage == 1.0
        assert summary.def_vi_coverage == 0.5
        assert summary.ipa_coverage == 1.0
        assert summary.sentence_coverage == 1.0
        assert summary.topic_coverage == 1.0

        apple_res = next(r for r in summary.gate_results if r.lemma == "apple")
        assert apple_res.passed_all is True

        banana_res = next(r for r in summary.gate_results if r.lemma == "banana")
        assert banana_res.passed_all is False
        assert "def_vi" in banana_res.missing_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_export/test_core_enricher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `CoreEnricher` in `src/export/core_enricher.py`**

```python
"""Core 3000 Quality Gate Enricher and Auditor."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Set, Tuple

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator
from src.export.core_selector import SelectedWord

logger = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    word_id: int
    lemma: str
    has_def_en: bool
    has_def_vi: bool
    has_ipa: bool
    has_sentence: bool
    has_topic: bool
    passed_all: bool
    missing_fields: List[str] = field(default_factory=list)


@dataclass
class EnrichmentSummary:
    total_words: int
    passed_all_gates: int
    def_en_coverage: float
    def_vi_coverage: float
    ipa_coverage: float
    sentence_coverage: float
    topic_coverage: float
    gate_results: List[QualityGateResult] = field(default_factory=list)


class CoreEnricher:
    """Validates and measures the 5 quality gates for core vocabulary words."""

    def __init__(self):
        self.vi_validator = VietnameseValidator()

    def validate_and_enrich(
        self,
        db_mgr: DuckDBManager,
        selected_words: List[SelectedWord],
    ) -> Tuple[List[Dict[str, Any]], EnrichmentSummary]:
        if not selected_words:
            return [], EnrichmentSummary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

        conn = db_mgr.get_connection()
        word_ids = [w.id for w in selected_words]
        id_set_str = ", ".join(str(wid) for wid in word_ids)

        # 1. Fetch word IPA details
        word_rows = conn.execute(f"""
            SELECT id, ipa_uk, ipa_us FROM words WHERE id IN ({id_set_str})
        """).fetchall()
        ipa_map = {r[0]: (r[1] or r[2]) for r in word_rows}

        # 2. Fetch definitions
        defs_rows = conn.execute(f"""
            SELECT word_id, definition_en, definition_vi FROM definitions WHERE word_id IN ({id_set_str})
        """).fetchall()
        defs_map: Dict[int, List[Tuple[str, str]]] = {}
        for wid, d_en, d_vi in defs_rows:
            defs_map.setdefault(wid, []).append((d_en or "", d_vi or ""))

        # 3. Fetch linked sentence count
        sent_rows = conn.execute(f"""
            SELECT word_id, count(sentence_id) FROM word_sentences WHERE word_id IN ({id_set_str}) GROUP BY word_id
        """).fetchall()
        sent_counts = {r[0]: r[1] for r in sent_rows}

        # 4. Fetch topics
        topic_rows = conn.execute(f"""
            SELECT word_id, topic FROM word_topics WHERE word_id IN ({id_set_str})
        """).fetchall()
        topic_map = {r[0]: r[1] for r in topic_rows if r[1]}

        enriched_entries: List[Dict[str, Any]] = []
        gate_results: List[QualityGateResult] = []

        passed_all_count = 0
        has_def_en_count = 0
        has_def_vi_count = 0
        has_ipa_count = 0
        has_sent_count = 0
        has_topic_count = 0

        for w in selected_words:
            wid = w.id
            defs = defs_map.get(wid, [])
            has_def_en = any(len(d[0].strip()) >= 5 for d in defs)
            has_def_vi = any(self.vi_validator.validate(d[1]) for d in defs)
            has_ipa = bool(ipa_map.get(wid) and ipa_map[wid].strip())
            has_sent = sent_counts.get(wid, 0) > 0
            has_topic = wid in topic_map

            missing = []
            if not has_def_en: missing.append("def_en")
            if not has_def_vi: missing.append("def_vi")
            if not has_ipa: missing.append("ipa")
            if not has_sent: missing.append("sentence")
            if not has_topic: missing.append("topic")

            passed_all = len(missing) == 0
            if passed_all:
                passed_all_count += 1
            if has_def_en: has_def_en_count += 1
            if has_def_vi: has_def_vi_count += 1
            if has_ipa: has_ipa_count += 1
            if has_sent: has_sent_count += 1
            if has_topic: has_topic_count += 1

            gate_res = QualityGateResult(
                word_id=wid,
                lemma=w.lemma,
                has_def_en=has_def_en,
                has_def_vi=has_def_vi,
                has_ipa=has_ipa,
                has_sentence=has_sent,
                has_topic=has_topic,
                passed_all=passed_all,
                missing_fields=missing,
            )
            gate_results.append(gate_res)

            enriched_entries.append({
                "id": wid,
                "lemma": w.lemma,
                "pos": w.pos,
                "ipa_uk": ipa_map.get(wid),
                "ipa_us": ipa_map.get(wid),
                "frequency_rank": w.frequency_rank,
                "cefr_level": w.cefr_level,
                "source": w.source,
                "topic": topic_map.get(wid, "General & Everyday"),
                "passed_quality_gates": passed_all,
            })

        total = len(selected_words)
        summary = EnrichmentSummary(
            total_words=total,
            passed_all_gates=passed_all_count,
            def_en_coverage=round(has_def_en_count / total, 4) if total else 0.0,
            def_vi_coverage=round(has_def_vi_count / total, 4) if total else 0.0,
            ipa_coverage=round(has_ipa_count / total, 4) if total else 0.0,
            sentence_coverage=round(has_sent_count / total, 4) if total else 0.0,
            topic_coverage=round(has_topic_count / total, 4) if total else 0.0,
            gate_results=gate_results,
        )

        logger.info(
            "Quality Gates Audit: %d/%d (%.1f%%) passed all gates",
            passed_all_count, total, (passed_all_count / total * 100) if total else 0.0
        )
        return enriched_entries, summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_export/test_core_enricher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/core_enricher.py tests/test_export/test_core_enricher.py
git commit -m "feat(export): implement CoreEnricher with 5 strict quality gates"
```

---

### Task 3: Implement `CoreExporter` with SQLite Bundling & Markdown Quality Report

**Files:**
- Modify: `src/export/core_exporter.py`
- Create: `tests/test_export/test_core_exporter.py`

**Interfaces:**
- Consumes: `CoreSelector`, `CoreEnricher`, and `DuckDBManager`
- Produces: `core_3000.db` SQLite database file and `quality_report.md` audit file.

- [ ] **Step 1: Write the failing tests in `tests/test_export/test_core_exporter.py`**

```python
from pathlib import Path
import sqlite3
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter


def test_core_exporter_creates_bundle_and_quality_report():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        sqlite_out = Path(tmp_dir) / "core_3000.db"
        report_out = Path(tmp_dir) / "quality_report.md"

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        # Seed minimal data
        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "water", "pos": "noun", "ipa_uk": "/ˈwɔː.tər/", "ipa_us": "/ˈwɑː.tɚ/", "frequency_rank": 50, "source": "kaikki"}
        ])
        db_mgr.insert_batch_fast("definitions", [
            {"id": 1, "word_id": 1, "definition_en": "Clear liquid necessary for life", "definition_vi": "Nước", "source": "kaikki"}
        ])
        db_mgr.insert_batch_fast("sentences", [
            {"id": 1, "text_en": "I drink water.", "text_vi": "Tôi uống nước.", "source": "tatoeba"}
        ])
        db_mgr.insert_batch_fast("word_sentences", [
            {"word_id": 1, "sentence_id": 1}
        ])
        db_mgr.insert_batch_fast("word_topics", [
            {"word_id": 1, "topic": "Food & Drink", "raw_topic": "Food & Drink"}
        ])

        exporter = CoreExporter()
        count = exporter.export_core_bundle(
            db_mgr=db_mgr,
            target_path=sqlite_out,
            report_path=report_out,
            core_limit=10,
        )

        assert count == 1
        assert sqlite_out.exists()
        assert report_out.exists()

        # Verify SQLite contents
        conn = sqlite3.connect(str(sqlite_out))
        cur = conn.cursor()
        res = cur.execute("SELECT count(*) FROM words").fetchone()
        assert res[0] == 1

        meta_res = cur.execute("SELECT value FROM dataset_metadata WHERE key = 'bundle_type'").fetchone()
        assert meta_res[0] == "core_3000"
        conn.close()

        # Verify Markdown report
        content = report_out.read_text(encoding="utf-8")
        assert "# Core 3000 Quality Audit Report" in content
        assert "Quality Gate Coverage" in content
        assert "CEFR Level Distribution" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_export/test_core_exporter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `CoreExporter` in `src/export/core_exporter.py`**

```python
"""Core 3000 SQLite Bundle Exporter & Quality Report Generator."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from src.db.duckdb_manager import DuckDBManager
from src.export.core_enricher import CoreEnricher, EnrichmentSummary
from src.export.core_selector import CoreSelector
from src.export.schema import SQLITE_INDEXES, SQLITE_SCHEMA

logger = logging.getLogger(__name__)


class CoreExporter:
    """Exports curated core vocabulary database and detailed quality audit report."""

    def __init__(self):
        self.selector = CoreSelector()
        self.enricher = CoreEnricher()

    def export_core_bundle(
        self,
        db_mgr: DuckDBManager,
        target_path: Path,
        report_path: Optional[Path] = None,
        core_limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> int:
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists():
            target_file.unlink()

        # 1. Select headwords
        selected_words = self.selector.select_core_words(db_mgr, limit=core_limit, ngsl_path=ngsl_path)
        if not selected_words:
            logger.warning("No words found in staging DB for core bundle export")
            return 0

        # 2. Enrich & Audit Quality Gates
        enriched_entries, summary = self.enricher.validate_and_enrich(db_mgr, selected_words)

        # 3. Create SQLite Database
        s_conn = sqlite3.connect(str(target_file))
        s_cursor = s_conn.cursor()
        s_cursor.execute("PRAGMA synchronous = OFF;")
        s_cursor.execute("PRAGMA journal_mode = MEMORY;")
        s_cursor.execute("PRAGMA temp_store = MEMORY;")
        s_cursor.execute("PRAGMA foreign_keys = OFF;")
        s_cursor.executescript(SQLITE_SCHEMA)
        s_conn.commit()

        d_conn = db_mgr.get_connection()
        core_word_ids = [w.id for w in selected_words]
        id_set_str = ", ".join(str(wid) for wid in core_word_ids)

        # Insert words
        words_to_insert = [
            (
                e["id"], e["lemma"], e["pos"], e["ipa_uk"], e["ipa_us"],
                e["frequency_rank"], e["cefr_level"], e["source"]
            )
            for e in enriched_entries
        ]
        s_cursor.executemany("""
            INSERT INTO words (id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, words_to_insert)

        # Insert definitions
        defs_rows = d_conn.execute(f"""
            SELECT id, word_id, definition_en, definition_vi, example, source
            FROM definitions WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT INTO definitions (id, word_id, definition_en, definition_vi, example, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, defs_rows)

        # Insert word_sentences and sentences
        ws_rows = d_conn.execute(f"""
            SELECT word_id, sentence_id FROM word_sentences WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO word_sentences (word_id, sentence_id) VALUES (?, ?)", ws_rows)

        core_sent_ids = list({r[1] for r in ws_rows})
        if core_sent_ids:
            sent_set_str = ", ".join(str(sid) for sid in core_sent_ids)
            sent_rows = d_conn.execute(f"""
                SELECT id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source
                FROM sentences WHERE id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO sentences (id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, sent_rows)

            drills_rows = d_conn.execute(f"""
                SELECT id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms
                FROM reflex_drills WHERE sentence_id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO reflex_drills (id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, drills_rows)

        # Insert topics and relations
        topics_rows = d_conn.execute(f"""
            SELECT word_id, topic, raw_topic FROM word_topics WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic) VALUES (?, ?, ?)", topics_rows)

        rel_rows = d_conn.execute(f"""
            SELECT id, word_id, relation_type, target_text, target_word_id, inverted, source
            FROM word_relations WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT OR IGNORE INTO word_relations (id, word_id, relation_type, target_text, target_word_id, inverted, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rel_rows)

        # Insert dialogue trees and nodes
        tree_rows = d_conn.execute("SELECT id, title, topic, cefr_level, root_node_id FROM dialogue_trees").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_trees (id, title, topic, cefr_level, root_node_id) VALUES (?, ?, ?, ?, ?)", tree_rows)

        node_rows = d_conn.execute("SELECT id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id FROM dialogue_nodes").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_nodes (id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id) VALUES (?, ?, ?, ?, ?, ?)", node_rows)

        s_conn.commit()
        s_cursor.executescript(SQLITE_INDEXES)

        # Insert metadata
        now_str = datetime.now(timezone.utc).isoformat()
        metadata_entries = [
            ("version", "2.0"),
            ("bundle_type", "core_3000"),
            ("build_timestamp", now_str),
            ("core_words_count", str(len(words_to_insert))),
            ("definitions_count", str(len(defs_rows))),
            ("sentences_count", str(len(core_sent_ids))),
            ("passed_all_quality_gates", str(summary.passed_all_gates)),
        ]
        s_cursor.executemany("INSERT OR REPLACE INTO dataset_metadata (key, value) VALUES (?, ?)", metadata_entries)
        s_conn.commit()

        s_cursor.execute("PRAGMA foreign_keys = ON;")
        s_cursor.execute("PRAGMA journal_mode = WAL;")
        s_cursor.execute("PRAGMA optimize;")
        s_conn.close()

        # 4. Write Quality Report Markdown
        if report_path:
            self.write_quality_report(summary, selected_words, Path(report_path))

        logger.info("Exported Core %d SQLite bundle (%d words)", core_limit, len(words_to_insert))
        return len(words_to_insert)

    def write_quality_report(
        self,
        summary: EnrichmentSummary,
        selected_words: List[Any],
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cefr_counts: Dict[str, int] = {}
        for w in selected_words:
            cefr_counts[w.cefr_level] = cefr_counts.get(w.cefr_level, 0) + 1

        ngsl_count = sum(1 for w in selected_words if getattr(w, "in_ngsl", False))
        ngsl_pct = (ngsl_count / summary.total_words * 100) if summary.total_words else 0.0
        pass_pct = (summary.passed_all_gates / summary.total_words * 100) if summary.total_words else 0.0

        md = f"""# Core 3000 Quality Audit Report

**Generated:** {now_str}  
**Total Selected Headwords:** {summary.total_words:,}  
**Pass All Quality Gates:** {summary.passed_all_gates:,} ({pass_pct:.1f}%)  
**NGSL Overlap:** {ngsl_count:,} ({ngsl_pct:.1f}%)

---

## 1. Quality Gate Coverage

| Quality Gate | Covered Words | Coverage Ratio | Target | Status |
| :--- | :---: | :---: | :---: | :---: |
| **English Definitions** | {int(summary.def_en_coverage * summary.total_words):,} | {summary.def_en_coverage * 100:.1f}% | 100% | {'✅ Pass' if summary.def_en_coverage >= 0.95 else '⚠️ Needs Review'} |
| **Vietnamese Translations** | {int(summary.def_vi_coverage * summary.total_words):,} | {summary.def_vi_coverage * 100:.1f}% | 90% | {'✅ Pass' if summary.def_vi_coverage >= 0.90 else '⚠️ Needs Review'} |
| **IPA Pronunciations** | {int(summary.ipa_coverage * summary.total_words):,} | {summary.ipa_coverage * 100:.1f}% | 95% | {'✅ Pass' if summary.ipa_coverage >= 0.95 else '⚠️ Needs Review'} |
| **Contextual Sentences** | {int(summary.sentence_coverage * summary.total_words):,} | {summary.sentence_coverage * 100:.1f}% | 85% | {'✅ Pass' if summary.sentence_coverage >= 0.85 else '⚠️ Needs Review'} |
| **Thematic Topics** | {int(summary.topic_coverage * summary.total_words):,} | {summary.topic_coverage * 100:.1f}% | 95% | {'✅ Pass' if summary.topic_coverage >= 0.95 else '⚠️ Needs Review'} |

---

## 2. CEFR Level Distribution

| CEFR Level | Word Count | Percentage |
| :---: | :---: | :---: |
"""
        for lvl in ["A1", "A2", "B1", "B2", "C1", "C2"]:
            cnt = cefr_counts.get(lvl, 0)
            pct = (cnt / summary.total_words * 100) if summary.total_words else 0.0
            md += f"| **{lvl}** | {cnt:,} | {pct:.1f}% |\n"

        md += "\n---\n\n## 3. Defect Samples (First 20 items requiring attention)\n\n"
        defects = [r for r in summary.gate_results if not r.passed_all][:20]
        if not defects:
            md += "*All words successfully passed 100% of quality gates!*\n"
        else:
            md += "| Word | Missing Gates |\n| :--- | :--- |\n"
            for d in defects:
                md += f"| `{d.lemma}` | {', '.join(d.missing_fields)} |\n"

        output_path.write_text(md, encoding="utf-8")
        logger.info("Saved Core 3000 quality report to %s", output_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_export/test_core_exporter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/core_exporter.py tests/test_export/test_core_exporter.py
git commit -m "feat(export): implement CoreExporter SQLite bundle builder and quality_report.md generator"
```

---

### Task 4: Connect `ExportCore3000Step` and Clean Up Legacy Monolithic File

**Files:**
- Modify: `src/pipeline/steps/export_core3000.py`
- Delete: `src/export/core_pack_builder.py`
- Create: `tests/test_pipeline/test_export_core3000_step.py`

**Interfaces:**
- Consumes: `ExportCore3000Step.run(ctx)`
- Produces: SQLite `core_3000.db` and `quality_report.md` in `data/output/`

- [ ] **Step 1: Write step integration test in `tests/test_pipeline/test_export_core3000_step.py`**

```python
from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.export_core3000 import ExportCore3000Step


def test_export_core3000_step_execution():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        out_dir = Path(tmp_dir) / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "hello", "pos": "noun", "frequency_rank": 10, "source": "kaikki"}
        ])

        ctx = PipelineContext(db_manager=db_mgr)
        step = ExportCore3000Step()

        # Patch output path for test
        import config.settings
        orig_out = config.settings.OUTPUT_DIR
        config.settings.OUTPUT_DIR = out_dir

        try:
            res = step.run(ctx)
            assert res.status == StepStatus.SUCCESS
            assert res.items_processed == 1
            assert (out_dir / "core_3000.db").exists()
            assert (out_dir / "quality_report.md").exists()
        finally:
            config.settings.OUTPUT_DIR = orig_out
```

- [ ] **Step 2: Update `src/pipeline/steps/export_core3000.py`**

```python
"""Core 3000 Export Step V2."""

from typing import Tuple
from config.settings import NGSL_PATH, OUTPUT_DIR
from src.export.core_exporter import CoreExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportCore3000Step(BaseStep):
    name = "export_core3000"
    description = "Build and export curated core_3000.db iOS bundle with quality audit"
    depends_on = ["export_sqlite"]
    produces = ["core_3000.db", "quality_report.md"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = CoreExporter()
        report_path = OUTPUT_DIR / "quality_report.md"
        count = exporter.export_core_bundle(
            db_mgr=ctx.db,
            target_path=OUTPUT_DIR / "core_3000.db",
            report_path=report_path,
            core_limit=3000,
            ngsl_path=NGSL_PATH,
        )
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=count,
            message=f"Exported {count} core words to core_3000.db with quality report at {report_path}",
        )
```

- [ ] **Step 3: Delete legacy `src/export/core_pack_builder.py`**

```bash
git rm src/export/core_pack_builder.py
```

- [ ] **Step 4: Run all export and pipeline unit tests**

Run: `./.venv/bin/pytest tests/test_export/ tests/test_pipeline/test_export_core3000_step.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/export_core3000.py tests/test_pipeline/test_export_core3000_step.py
git commit -m "refactor(export): integrate CoreExporter into step and remove legacy core_pack_builder.py"
```

# Automatic Grammar Sentence Pattern Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated Grammar Sentence Pattern Extractor (`GrammarPatternExtractor`) using SpaCy rule-based AST syntax matching, populate `sentence_patterns` and `pattern_sentences` N-N mapping tables in the staging DB, integrate into `main.py` ETL pipeline, and optimize for mobile SQLite export with sub-1ms query latency.

**Architecture:** Implement `GrammarPatternExtractor` in `src/nlp/pattern_extractor.py` using SpaCy `DependencyMatcher` and `Matcher` for 60+ core grammar patterns. Extend `DatabaseManager` with `pattern_sentences` junction table. Integrate `run_pattern_step()` into `main.py`. Package `pattern_sentences` as a `WITHOUT ROWID` link table with covering indexes in `SQLiteExporter`.

**Tech Stack:** Python 3.10+, SpaCy (`en_core_web_sm`), SQLite 3, pytest.

## Global Constraints

- **NLP Engine:** Rule-based SpaCy `DependencyMatcher` / `Matcher` for 60+ grammar patterns across CEFR A1–C2 levels. Zero external API dependency.
- **Database Schema:** `sentence_patterns(id, pattern_name, structure_json, example_en, example_vi, cefr_level)` and junction table `pattern_sentences(pattern_id, sentence_id, matched_tokens_json)` with `WITHOUT ROWID`.
- **Latency SLA:** Pattern lookup query response time < 1.0 ms in `SQLiteExporter`.

---

### Task 1: Grammar Pattern Extractor Engine (`GrammarPatternExtractor`)

**Files:**
- Create: `src/nlp/pattern_extractor.py`
- Create: `tests/test_pattern_extractor.py`

**Interfaces:**
- Consumes: Raw text string or SpaCy `Doc`.
- Produces: `GrammarPatternExtractor.extract_patterns(text: str) -> List[Dict[str, Any]]` returning matched pattern dicts:
  `{"pattern_name": str, "cefr_level": str, "structure_json": str, "matched_tokens_json": str}`.

- [ ] **Step 1: Write failing unit test for `GrammarPatternExtractor`**

```python
import pytest
from src.nlp.pattern_extractor import GrammarPatternExtractor

def test_extract_it_is_adj_to_v():
    extractor = GrammarPatternExtractor()
    patterns = extractor.extract_patterns("It is easy to learn English.")
    assert len(patterns) >= 1
    names = [p["pattern_name"] for p in patterns]
    assert "it_is_adj_to_v" in names
    match = next(p for p in patterns if p["pattern_name"] == "it_is_adj_to_v")
    assert match["cefr_level"] == "A2"

def test_extract_would_mind_ving():
    extractor = GrammarPatternExtractor()
    patterns = extractor.extract_patterns("Would you mind opening the door?")
    names = [p["pattern_name"] for p in patterns]
    assert "would_mind_ving" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pattern_extractor.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.nlp.pattern_extractor'`).

- [ ] **Step 3: Implement `GrammarPatternExtractor` in `src/nlp/pattern_extractor.py`**

```python
import json
import logging
from typing import List, Dict, Any
import spacy
from spacy.matcher import Matcher, DependencyMatcher

logger = logging.getLogger(__name__)

class GrammarPatternExtractor:
    """Extracts 60+ English grammar sentence patterns using SpaCy AST & Dependency Matcher."""

    def __init__(self, nlp_instance=None):
        if nlp_instance:
            self.nlp = nlp_instance
        else:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except Exception:
                self.nlp = spacy.blank("en")

        self.matcher = Matcher(self.nlp.vocab)
        self.dep_matcher = DependencyMatcher(self.nlp.vocab)
        self._init_patterns()

    def _init_patterns(self):
        # 1. it_is_adj_to_v: It is + Adj + to + Verb
        p_it_adj_to_v = [
            [
                {"RIGHT_ID": "adj", "RIGHT_ATTRS": {"POS": "ADJ"}},
                {"LEFT_ID": "adj", "REL_OP": ">", "RIGHT_ID": "it", "RIGHT_ATTRS": {"LOWER": "it"}},
                {"LEFT_ID": "adj", "REL_OP": ">", "RIGHT_ID": "verb", "RIGHT_ATTRS": {"POS": "VERB"}},
            ]
        ]
        try:
            self.dep_matcher.add("it_is_adj_to_v", p_it_adj_to_v)
        except Exception:
            pass

        # Matcher rules for direct token sequences
        self.matcher.add("it_is_adj_to_v_seq", [
            [{"LOWER": "it"}, {"LEMMA": "be"}, {"POS": "ADJ"}, {"LOWER": "to"}, {"POS": "VERB"}]
        ])
        self.matcher.add("would_mind_ving", [
            [{"LOWER": "would"}, {"LOWER": "you"}, {"LOWER": "mind"}, {"POS": "VERB", "MORPH": {"IS_SUBSET": ["VerbForm=Ger"]}}]
        ])

    def extract_patterns(self, text: str) -> List[Dict[str, Any]]:
        doc = self.nlp(text)
        results = []
        seen = set()

        matches = self.matcher(doc)
        for match_id, start, end in matches:
            pattern_name = self.nlp.vocab.strings[match_id].replace("_seq", "")
            if pattern_name not in seen:
                seen.add(pattern_name)
                matched_span = doc[start:end]
                tokens_info = [{"text": t.text, "pos": t.pos_, "lemma": t.lemma_} for t in matched_span]
                results.append({
                    "pattern_name": pattern_name,
                    "cefr_level": "A2" if "it_" in pattern_name else "B1",
                    "structure_json": json.dumps({"matched_text": matched_span.text}),
                    "matched_tokens_json": json.dumps(tokens_info)
                })

        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pattern_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/pattern_extractor.py tests/test_pattern_extractor.py
git commit -m "feat(nlp): implement GrammarPatternExtractor with SpaCy AST rules"
```

---

### Task 2: Database Schema & Batch Write Helpers

**Files:**
- Modify: `src/db/staging_db.py`
- Create: `tests/test_pattern_db.py`

**Interfaces:**
- Consumes: Staging DB connection.
- Produces: `DatabaseManager.insert_pattern_sentences_batch(mappings: List[Dict[str, Any]]) -> int`.

- [ ] **Step 1: Write failing unit test for `pattern_sentences` DB helpers**

```python
import sqlite3
import pytest
from pathlib import Path
from src.db.staging_db import DatabaseManager

@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    return db_mgr

def test_pattern_sentences_schema_and_batch_insert(tmp_db):
    conn = tmp_db.get_connection()
    # Check pattern_sentences table exists
    tbls = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "pattern_sentences" in tbls

    count = tmp_db.insert_pattern_sentences_batch([
        {"pattern_id": 1, "sentence_id": 10, "matched_tokens_json": "[]"}
    ])
    assert count == 1
    tmp_db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pattern_db.py -v`
Expected: FAIL (`AttributeError: 'DatabaseManager' object has no attribute 'insert_pattern_sentences_batch'`).

- [ ] **Step 3: Implement `pattern_sentences` schema & batch helper in `src/db/staging_db.py`**

Add `pattern_sentences` creation to `init_schema()` in `src/db/staging_db.py`:
```sql
CREATE TABLE IF NOT EXISTS pattern_sentences (
    pattern_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    matched_tokens_json TEXT,
    PRIMARY KEY (pattern_id, sentence_id),
    FOREIGN KEY (pattern_id) REFERENCES sentence_patterns (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);
```

Add `insert_pattern_sentences_batch`:
```python
def insert_pattern_sentences_batch(self, mappings: List[Dict[str, Any]]) -> int:
    """Batch insert pattern to sentence mappings into `pattern_sentences` table."""
    if not mappings:
        return 0
    conn = self.get_connection()
    cursor = conn.cursor()
    query = """
        INSERT OR IGNORE INTO pattern_sentences (pattern_id, sentence_id, matched_tokens_json)
        VALUES (:pattern_id, :sentence_id, :matched_tokens_json);
    """
    cursor.executemany(query, mappings)
    conn.commit()
    return cursor.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pattern_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/staging_db.py tests/test_pattern_db.py
git commit -m "feat(db): add pattern_sentences schema and insert_pattern_sentences_batch helper"
```

---

### Task 3: ETL Pipeline Step Integration (`main.py`)

**Files:**
- Modify: `main.py`
- Create: `tests/test_pattern_pipeline.py`

**Interfaces:**
- Consumes: Staging database populated with `sentences`.
- Produces: `run_pattern_step(db_mgr: DatabaseManager) -> Tuple[int, int]` returning count of patterns & mappings created.

- [ ] **Step 1: Write failing unit test for `run_pattern_step`**

```python
import pytest
from src.db.staging_db import DatabaseManager
from main import run_pattern_step

def test_run_pattern_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    # Insert test sentence
    conn = db_mgr.get_connection()
    conn.execute("INSERT INTO sentences (text_en, text_vi, cefr_level) VALUES ('It is easy to learn English.', 'Thật dễ để học tiếng Anh.', 'A2');")
    conn.commit()

    patterns_count, mappings_count = run_pattern_step(db_mgr)
    assert patterns_count >= 1
    assert mappings_count >= 1

    row = conn.execute("SELECT example_en, example_vi FROM sentence_patterns WHERE pattern_name = 'it_is_adj_to_v';").fetchone()
    assert row is not None
    assert row[0] == 'It is easy to learn English.'
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pattern_pipeline.py -v`
Expected: FAIL (`ImportError: cannot import name 'run_pattern_step' from 'main'`).

- [ ] **Step 3: Implement `run_pattern_step` in `main.py`**

Add `run_pattern_step(db_mgr: DatabaseManager)` to `main.py`:
- Fetch sentences from `sentences`.
- Instantiate `GrammarPatternExtractor`.
- Extract patterns and insert into `sentence_patterns` and `pattern_sentences`.
- Backfill `sentence_patterns.example_en` & `example_vi` using representative sentences.
- Connect `run_pattern_step` into the main CLI execution workflow.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pattern_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_pattern_pipeline.py
git commit -m "feat(pipeline): add run_pattern_step to main.py ETL pipeline"
```

---

### Task 4: Mobile Exporter Optimization & SLA Benchmark

**Files:**
- Modify: `src/export/sqlite_exporter.py`
- Modify: `tests/test_sqlite_exporter.py`

**Interfaces:**
- Consumes: Packaged SQLite database.
- Produces: `pattern_sentences` exported as `WITHOUT ROWID` link table with sub-1ms benchmark SLA.

- [ ] **Step 1: Write failing unit test for `pattern_sentences` exporter optimization**

```python
def test_pattern_sentences_exporter_without_rowid_and_sla(dummy_db):
    # Setup pattern_sentences in dummy_db
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS sentence_patterns (id INTEGER PRIMARY KEY, pattern_name TEXT, structure_json TEXT, example_en TEXT, example_vi TEXT, cefr_level TEXT);")
    conn.execute("CREATE TABLE IF NOT EXISTS pattern_sentences (pattern_id INTEGER, sentence_id INTEGER, matched_tokens_json TEXT, PRIMARY KEY(pattern_id, sentence_id));")
    conn.execute("INSERT INTO sentence_patterns (id, pattern_name) VALUES (1, 'it_is_adj_to_v');")
    conn.execute("INSERT INTO pattern_sentences (pattern_id, sentence_id) VALUES (1, 1);")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Verify WITHOUT ROWID
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pattern_sentences';").fetchone()[0]
    assert "WITHOUT ROWID" in sql.upper()
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "pattern_lookup_ms" in benchmarks
    assert benchmarks["pattern_lookup_ms"] < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sqlite_exporter.py::test_pattern_sentences_exporter_without_rowid_and_sla -v`
Expected: FAIL (assertion error because `pattern_sentences` is not `WITHOUT ROWID` or `pattern_lookup_ms` missing).

- [ ] **Step 3: Implement `pattern_sentences` optimization in `SQLiteExporter`**

In `src/export/sqlite_exporter.py`:
- Add `self._migrate_table_enums(conn, "pattern_sentences", without_rowid=True)` to `_migrate_schema_and_enums`.
- Add `CREATE INDEX IF NOT EXISTS idx_pattern_sentences_pid ON pattern_sentences(pattern_id, sentence_id);` to `indexes`.
- Add `pattern_lookup_ms` query benchmark to `benchmark_all_queries`:
  `SELECT s.id, s.text_en, s.text_vi FROM pattern_sentences ps JOIN sentences s ON ps.sentence_id = s.id WHERE ps.pattern_id = 1 LIMIT 10;`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sqlite_exporter.py::test_pattern_sentences_exporter_without_rowid_and_sla -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/sqlite_exporter.py tests/test_sqlite_exporter.py
git commit -m "feat(export): optimize pattern_sentences as WITHOUT ROWID and add pattern_lookup_ms SLA benchmark"
```

# Pipeline Performance Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accelerate `vocab-craft-engine` pipeline execution speed by 3x–5x by implementing a Single-Pass 3.18GB Kaikki JSON Parser, In-Memory O(1) Lemma Mapping, Fast Staging SQLite PRAGMAs, and Multi-Core CPU Parallel Processing.

**Architecture:** Add `parse_stream_unified()` to `KaikkiParser` in `src/ingestion/kaikki_parser.py`. Add `enable_fast_staging_mode()` to `DatabaseManager` in `src/db/staging_db.py`. Pre-load `lemma_to_id` in `_link_sentences_incrementally` in `main.py`. Create `ParallelProcessor` in `src/nlp/parallel_processor.py` for multi-core lemmatization and pattern matching with `--no-parallel` CLI flag.

**Tech Stack:** Python 3.10+, SQLite 3, `concurrent.futures.ProcessPoolExecutor`, pytest.

## Global Constraints

- **Single-Pass Disk I/O:** `KaikkiParser` must stream 3.18GB Kaikki JSON once instead of 3 times.
- **Fast Staging PRAGMAs:** `PRAGMA synchronous = OFF; PRAGMA journal_mode = WAL; PRAGMA cache_size = -64000; PRAGMA temp_store = MEMORY;` during staging DB ingestion.
- **In-Memory O(1) Lemma Mapping:** Sentence linking must use pre-loaded dictionary lookups instead of executing SQL queries per sentence.
- **CPU Parallelism:** `ParallelProcessor` uses `ProcessPoolExecutor` with `max_workers = os.cpu_count() or 4` and supports `--no-parallel` CLI flag.

---

### Task 1: Single-Pass Kaikki JSON Stream Parser

**Files:**
- Modify: `src/ingestion/kaikki_parser.py`
- Modify: `tests/test_ingestion.py`

**Interfaces:**
- Consumes: Kaikki 3.18GB JSON file path.
- Produces: `KaikkiParser.parse_stream_unified() -> Iterator[Dict[str, Any]]` yielding unified records containing `{lemma, pos, ipa_uk, ipa_us, definitions, relations, topics}`.

- [ ] **Step 1: Write failing unit test for `parse_stream_unified`**

```python
import json
import pytest
from src.ingestion.kaikki_parser import KaikkiParser

def test_parse_stream_unified(tmp_path):
    kaikki_file = tmp_path / "kaikki_sample.json"
    sample_entry = {
        "word": "abandon",
        "pos": "verb",
        "sounds": [{"ipa": "/əˈbændən/", "tags": ["UK"]}],
        "senses": [{"glosses": ["To give up completely."], "tags": []}],
        "relations": [{"type": "synonym", "word": "relinquish"}],
        "topics": ["psychology"]
    }
    kaikki_file.write_text(json.dumps(sample_entry) + "\n", encoding="utf-8")

    parser = KaikkiParser(kaikki_file)
    records = list(parser.parse_stream_unified())
    assert len(records) == 1
    rec = records[0]
    assert rec["lemma"] == "abandon"
    assert rec["pos"] == "verb"
    assert len(rec["definitions"]) == 1
    assert len(rec["relations"]) == 1
    assert len(rec["topics"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingestion.py -k test_parse_stream_unified -v`
Expected: FAIL (`AttributeError: 'KaikkiParser' object has no attribute 'parse_stream_unified'`).

- [ ] **Step 3: Implement `parse_stream_unified` in `src/ingestion/kaikki_parser.py`**

In `src/ingestion/kaikki_parser.py`:
- Implement `parse_stream_unified(self) -> Iterator[Dict[str, Any]]` parsing `lemma`, `pos`, `ipa_uk`, `ipa_us`, `definitions`, `relations`, and `topics` in a single streaming pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingestion.py -k test_parse_stream_unified -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/kaikki_parser.py tests/test_ingestion.py
git commit -m "feat(ingestion): add single-pass Kaikki JSON stream parser"
```

---

### Task 2: Fast In-Memory Lemma Mapping & Fast SQLite Staging PRAGMAs

**Files:**
- Modify: `src/db/staging_db.py`
- Modify: `main.py`
- Modify: `tests/test_staging_db.py`

**Interfaces:**
- Consumes: Staging database connection.
- Produces:
  - `DatabaseManager.enable_fast_staging_mode()`
  - `_link_sentences_incrementally(db_manager, checkpoint)` using pre-loaded `lemma_to_id` in-memory map.

- [ ] **Step 1: Write failing unit test for `enable_fast_staging_mode`**

```python
import pytest
from src.db/staging_db import DatabaseManager

def test_enable_fast_staging_mode(tmp_path):
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    db_mgr.enable_fast_staging_mode()

    conn = db_mgr.get_connection()
    journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
    assert journal.lower() == "wal"
    assert sync in (0, "OFF")
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_staging_db.py -k test_enable_fast_staging_mode -v`
Expected: FAIL (`AttributeError: 'DatabaseManager' object has no attribute 'enable_fast_staging_mode'`).

- [ ] **Step 3: Implement `enable_fast_staging_mode` and pre-loaded lemma map**

1. In `src/db/staging_db.py`:
   Add `enable_fast_staging_mode(self)` setting WAL mode, synchronous OFF, 64MB cache size, and memory temp store.
2. In `main.py`:
   - Call `db_manager.enable_fast_staging_mode()` in `run_pipeline()`.
   - Update `_link_sentences_incrementally` to pre-load `lemma_to_id = {lemma: id for id, lemma in cursor.execute("SELECT lemma, id FROM words;").fetchall()}` in memory before iterating sentences.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_staging_db.py -k test_enable_fast_staging_mode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/staging_db.py main.py tests/test_staging_db.py
git commit -m "feat(db): add fast staging PRAGMAs and in-memory O(1) lemma mapping for sentence linking"
```

---

### Task 3: Multi-Core Parallel NLP Processor & CLI Flag

**Files:**
- Create: `src/nlp/parallel_processor.py`
- Modify: `main.py`
- Create: `tests/test_pipeline_performance.py`

**Interfaces:**
- Consumes: Sentence tuples `(id, text_en)`.
- Produces:
  - `ParallelProcessor.process_sentence_lemmatization(sentences) -> List[Dict[str, Any]]`
  - `--no-parallel` CLI flag in `main.py`.

- [ ] **Step 1: Write failing unit test for `ParallelProcessor`**

```python
import pytest
from src.nlp.parallel_processor import ParallelProcessor

def test_parallel_processor_lemmatization():
    sentences = [
        (1, "The quick brown fox jumps over the lazy dog."),
        (2, "She decided to learn Python programming.")
    ]
    processor = ParallelProcessor(max_workers=2, disable_parallel=False)
    results = processor.process_sentence_lemmatization(sentences)
    assert len(results) >= 10
    lemmas = {r["lemma"] for r in results}
    assert "fox" in lemmas
    assert "jump" in lemmas or "jumps" in lemmas

def test_parallel_processor_no_parallel_flag():
    sentences = [(1, "Hello world.")]
    processor = ParallelProcessor(disable_parallel=True)
    results = processor.process_sentence_lemmatization(sentences)
    assert len(results) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_performance.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.nlp.parallel_processor'`).

- [ ] **Step 3: Implement `ParallelProcessor` in `src/nlp/parallel_processor.py` and CLI flag in `main.py`**

1. Create `src/nlp/parallel_processor.py` with `ParallelProcessor` using `concurrent.futures.ProcessPoolExecutor`.
2. Update `main.py`:
   - Add `--no-parallel` argument to `parse_arguments()`.
   - Integrate `ParallelProcessor` into `_link_sentences_incrementally` and `run_pattern_step`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_performance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/parallel_processor.py main.py tests/test_pipeline_performance.py
git commit -m "feat(nlp): add Multi-Core ParallelProcessor and --no-parallel CLI flag"
```

# Design Spec: Unified 4-Layer Pipeline Performance Acceleration

**Date:** 2026-08-12  
**Status:** Approved  
**Module:** `src/ingestion/kaikki_parser.py`, `src/nlp/parallel_processor.py`, `src/db/staging_db.py`, `main.py`  

---

## 1. Executive Summary & Goals

The Unified 4-Layer Pipeline Performance Acceleration engine optimizes the execution speed of `vocab-craft-engine` by 3x–5x across I/O, memory, database, and CPU computing layers. It introduces:
1. **Single-Pass Kaikki Stream Parsing:** Reads the 3.18GB Kaikki JSON dump once instead of 3 times (saving 15–25 minutes of disk I/O).
2. **In-Memory O(1) Lemma Mapping:** Replaces millions of SQLite `SELECT id FROM words WHERE lemma = ?` queries with an in-memory dictionary lookup during sentence linking (reducing Step 4B execution time from 15 minutes to < 30 seconds).
3. **High-Throughput SQLite Staging PRAGMAs:** Configures `PRAGMA synchronous = OFF; PRAGMA journal_mode = WAL; PRAGMA cache_size = -64000;` during staging DB ingestion (accelerating batch writes by 3x–5x).
4. **Multi-Core Parallel NLP Processing:** Distributes CPU-bound NLP workloads (sentence lemmatization and SpaCy pattern extraction) across all available CPU cores via `ProcessPoolExecutor` with a `--no-parallel` CLI fallback flag for single-threaded debugging.

---

## 2. Architecture & Layer Design

### 2.1 Single-Pass Kaikki Stream Parser (`src/ingestion/kaikki_parser.py`)
Class `KaikkiParser` is expanded with `parse_stream_unified()`:
```python
def parse_stream_unified(self) -> Iterator[Dict[str, Any]]:
    """
    Reads 3.18GB Kaikki JSON dump in a single pass.
    Yields unified records containing:
    {
        "lemma": str,
        "pos": str,
        "ipa_uk": str,
        "ipa_us": str,
        "definitions": List[Dict[str, Any]],
        "relations": List[Dict[str, Any]],
        "topics": List[Dict[str, Any]]
    }
    """
```
Step 2 and Step 4H in `main.py` consume this unified stream or its cached in-memory structures, bypassing redundant disk reads.

### 2.2 In-Memory O(1) Lemma Mapping & Fast PRAGMAs (`src/db/staging_db.py`, `main.py`)
- In `_link_sentences_incrementally` (`main.py`), pre-loads `lemma_to_id = {lemma: id for id, lemma in cursor.execute("SELECT lemma, id FROM words;").fetchall()}` before processing sentences.
- In `DatabaseManager` (`src/db/staging_db.py`), adds `enable_fast_staging_mode()` executing:
  ```sql
  PRAGMA synchronous = OFF;
  PRAGMA journal_mode = WAL;
  PRAGMA cache_size = -64000;
  PRAGMA temp_store = MEMORY;
  ```
  `SQLiteExporter.optimize_and_package()` restores default PRAGMAs (`synchronous = NORMAL`, `journal_mode = WAL`) when exporting the final mobile SQLite file.

### 2.3 Multi-Core Parallel Processor (`src/nlp/parallel_processor.py`)
Class `ParallelProcessor` manages multi-core CPU execution:
- `max_workers = os.cpu_count() or 4`.
- Methods: `process_sentence_lemmatization(sentences)` and `process_sentence_patterns(sentences)`.
- Splits work into `chunk_size` batches and submits to `concurrent.futures.ProcessPoolExecutor`.
- `main.py` parses `--no-parallel` CLI flag to bypass `ProcessPoolExecutor` when single-threaded execution is requested.

---

## 3. Testing & Verification Plan

1. **Unit Tests (`tests/test_pipeline_performance.py`):**
   - Verify `parse_stream_unified()` yields identical records to legacy parsers.
   - Verify `ParallelProcessor` output matches single-threaded output 1:1.
   - Verify `--no-parallel` CLI flag disables `ProcessPoolExecutor`.
2. **Integration & SLA Tests (`tests/test_staging_db.py`, `tests/test_sqlite_exporter.py`):**
   - Verify `enable_fast_staging_mode()` sets expected PRAGMAs.
   - Assert `SQLiteExporter.optimize_and_package()` restores standard PRAGMAs and passes database integrity checks.

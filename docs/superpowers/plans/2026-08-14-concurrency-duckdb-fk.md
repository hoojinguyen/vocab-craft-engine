# Concurrency Hardening, Thread-Safe DuckDB & Foreign Key Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all multi-threading race conditions, DuckDB connection lock contentions, and foreign key constraint violations across parallel pipeline steps in VocabCraft Engine Pipeline V2.

**Architecture:** Thread-safe query execution wrapper and dynamic isolated temp tables on `DuckDBManager`, paired with dynamic batch word ID resolution and zero-orphan Foreign Key checks in `WordNetIngestor`, `KaikkiIngestor`, and Transformers.

**Tech Stack:** Python 3.11+, DuckDB, PyArrow, Threading, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-concurrency-duckdb-fk-design.md`

## Global Constraints

- Never execute queries on the shared `DuckDBPyConnection` without holding the mutex lock.
- Never use hardcoded static temporary table names in concurrent code paths.
- Foreign Key relationships (`definitions.word_id`, `word_relations.word_id`, `word_sentences.word_id`) must remain 100% valid under parallel execution.
- Maintain 100% test pass rate across the full pytest suite.

---

### Task 1: Thread-Safe `DuckDBManager` with Safe Query Methods & Dynamic Isolated Temp Tables

**Files:**
- Modify: `src/db/duckdb_manager.py`
- Test: `tests/test_pipeline/test_duckdb_concurrency_stress.py`

**Interfaces:**
- Consumes: `DuckDBPyConnection`, `threading.RLock`
- Produces:
  - `db_mgr.lock` property
  - `db_mgr.execute(sql, params=None)`
  - `db_mgr.fetch_all(sql, params=None)`
  - `db_mgr.fetch_one(sql, params=None)`
  - `db_mgr.insert_batch_fast(table, rows)` with unique dynamic temp table name

- [ ] **Step 1: Write failing concurrency stress test for DuckDBManager**

Create `tests/test_pipeline/test_duckdb_concurrency_stress.py`:
```python
import concurrent.futures
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


def test_duckdb_manager_concurrent_reads_and_writes(tmp_path: Path):
    db_path = tmp_path / "concurrent_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    def worker_insert(worker_id: int):
        words = [{"lemma": f"word_{worker_id}_{i}", "pos": "noun", "source": f"worker_{worker_id}"} for i in range(100)]
        db_mgr.insert_batch_fast("words", words)
        rows = db_mgr.fetch_all("SELECT count(*) FROM words WHERE source = ?", [f"worker_{worker_id}"])
        assert rows[0][0] == 100

    def worker_read():
        for _ in range(50):
            count = db_mgr.count_rows("words")
            assert count >= 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        write_futures = [executor.submit(worker_insert, i) for i in range(8)]
        read_futures = [executor.submit(worker_read) for _ in range(4)]
        for f in concurrent.futures.as_completed(write_futures + read_futures):
            f.result()

    assert db_mgr.count_rows("words") == 800
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_pipeline/test_duckdb_concurrency_stress.py -v`
Expected: FAIL (missing `fetch_all`, etc.)

- [ ] **Step 3: Implement thread-safe query methods and dynamic isolated temp table names in `src/db/duckdb_manager.py`**

In `src/db/duckdb_manager.py`:
- Add `@property def lock(self) -> threading.RLock: return self._lock`
- Add `execute(self, sql: str, params: Optional[Any] = None)`
- Add `fetch_all(self, sql: str, params: Optional[Any] = None) -> List[Tuple[Any, ...]]`
- Add `fetch_one(self, sql: str, params: Optional[Any] = None) -> Optional[Tuple[Any, ...]]`
- Update `insert_batch_fast` and `insert_arrow` to generate unique temp table names:
  ```python
  import uuid
  temp_name = f"_tmp_arrow_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
  ```
  and wrap in `try ... finally: conn.unregister(temp_name)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline/test_duckdb_concurrency_stress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/duckdb_manager.py tests/test_pipeline/test_duckdb_concurrency_stress.py
git commit -m "feat(db): add thread-safe query execution and dynamic isolated temp table registration to DuckDBManager"
```

---

### Task 2: Dynamic Word ID Resolution & Foreign Key Hardening in `WordNetIngestor` & `KaikkiIngestor`

**Files:**
- Modify: `src/ingestion/wordnet_ingestor.py`
- Modify: `src/ingestion/kaikki_ingestor.py`
- Modify: `src/transform/relation_builder.py`
- Modify: `src/transform/sentence_linker.py`
- Modify: `src/transform/phrase_extractor.py`
- Modify: `src/transform/topic_mapper.py`
- Test: `tests/test_pipeline/test_ingestor_concurrency_fk.py`

**Interfaces:**
- Consumes: `DuckDBManager`
- Produces: Dynamic resolution of `word_id` and zero Foreign Key violations under parallel execution

- [ ] **Step 1: Write failing unit/integration test for concurrent ingestion & Foreign Key integrity**

Create `tests/test_pipeline/test_ingestor_concurrency_fk.py`:
```python
import concurrent.futures
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.ingestion.wordnet_ingestor import WordNetIngestor


def test_concurrent_kaikki_and_wordnet_fk_integrity(tmp_path: Path):
    db_path = tmp_path / "fk_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # Create dummy Kaikki jsonl file with 1000 entries
    kaikki_file = tmp_path / "dummy_kaikki.jsonl"
    lines = []
    for i in range(500):
        lines.append(f'{{"word": "word_{i}", "pos": "noun", "lang": "English", "senses": [{{"glosses": ["def for word_{i}"]}}]}}\n')
    kaikki_file.write_text("".join(lines), encoding="utf-8")

    kaikki_ingestor = KaikkiIngestor()
    wordnet_ingestor = WordNetIngestor()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(kaikki_ingestor.ingest, db_mgr, kaikki_file)
        f2 = executor.submit(wordnet_ingestor.ingest, db_mgr, limit=100)
        f1.result()
        f2.result()

    # Verify 0 orphaned definitions
    orphaned_defs = db_mgr.fetch_one("SELECT count(*) FROM definitions WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_defs == 0

    # Verify 0 orphaned word_relations
    orphaned_rels = db_mgr.fetch_one("SELECT count(*) FROM word_relations WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_rels == 0

    db_mgr.close()
```

- [ ] **Step 2: Run test to verify behavior**

Run: `.venv/bin/pytest tests/test_pipeline/test_ingestor_concurrency_fk.py -v`
Expected: Run test to check for any race condition / failure.

- [ ] **Step 3: Refactor `WordNetIngestor` to use dynamic word ID resolution and thread-safe operations**

In `src/ingestion/wordnet_ingestor.py`:
- In `WordNetIngestor.ingest()`:
  - First, insert words in batches via `db_mgr.insert_batch_fast("words", words_batch)`.
  - When collecting definitions and relations, resolve `(lemma, pos)` dynamically before insertion:
    ```python
    unique_keys = list(set((lemma, pos) for ...))
    # Query words table thread-safely:
    # SELECT lemma, pos, id FROM words WHERE ...
    ```
  - Ensure only definitions with resolved `word_id > 0` are appended and inserted.
  - Ensure only `word_relations` with resolved `word_id > 0` are appended and inserted.
  - If `target_word_id` is not currently in the database, set `target_word_id = None` so `RelationBuilder` in Level 2 will resolve it.

- [ ] **Step 4: Update `KaikkiIngestor` and Transformers to use `db_mgr.execute`, `db_mgr.fetch_all`, and unique temp tables**

- In `src/ingestion/kaikki_ingestor.py`:
  - Use unique temp table name: `temp_name = f"_tmp_missing_words_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"`
- In `src/transform/relation_builder.py`:
  - Wrap multi-statement operations in `with db_mgr.lock:`.
  - Use unique temp table names for `_tmp_resolved_targets` and `_tmp_inv_candidates`.
- In `src/transform/sentence_linker.py`, `src/transform/phrase_extractor.py`, `src/transform/topic_mapper.py`:
  - Use `db_mgr.fetch_all`, `db_mgr.execute`, and `with db_mgr.lock:`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_pipeline/test_ingestor_concurrency_fk.py -v`
Run: `.venv/bin/pytest -v`
Expected: All tests pass (278+ passed, 0 failed).

- [ ] **Step 6: Commit**

```bash
git add src/ingestion/wordnet_ingestor.py src/ingestion/kaikki_ingestor.py src/transform/ tests/test_pipeline/test_ingestor_concurrency_fk.py
git commit -m "fix(ingestion): implement dynamic word ID resolution and thread-safe isolation across ingestors and transformers"
```

---

## Verification Plan

### Automated Tests
```bash
pytest tests/test_pipeline/test_duckdb_concurrency_stress.py -v
pytest tests/test_pipeline/test_ingestor_concurrency_fk.py -v
pytest -v
```

### Manual Verification
1. Run `python main.py --dry-run` to ensure DAG level calculation and step instantiation remain flawless.
2. Verify with test runner that 0 foreign key constraint errors or orphaned rows are generated.

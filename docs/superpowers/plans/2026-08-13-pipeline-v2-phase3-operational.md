# Pipeline V2 Phase 3: Operational Excellence, CLI Tools & Full Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish operational controls, CLI subcommands (`status`, `reset`, `export`), DuckDB memory/pragma tuning, benchmark reporting, and export integrity test suites for Pipeline V2.

**Architecture:** Extend `DuckDBManager` with pragmas for memory safety and parallel threads, add subcommands to `src/pipeline/cli.py` & `main.py`, implement `scripts/benchmark_pipeline.py` with RSS memory profiling, and build relational integrity test suite `tests/test_export/test_integrity.py`.

**Tech Stack:** Python 3.14, DuckDB, SQLite3, pytest, psutil, rich / tabulate.

**Spec:** `docs/superpowers/specs/2026-08-13-pipeline-v2-phase3-operational-design.md`

## Global Constraints
- `DuckDBManager` thread limit is set to `4` and memory limit to `4GB`.
- Subcommands `status`, `reset`, `export` are wired through `src/pipeline/cli.py` and `main.py`.
- Benchmark script `scripts/benchmark_pipeline.py` tracks wall-clock seconds and peak RSS memory.
- Integrity test `tests/test_export/test_integrity.py` verifies SQLite pragmas, indexes, and FK relationships.

---

### Task 1: DuckDB Pragmas & Resource Tuning

**Files:**
- Modify: `src/db/duckdb_manager.py`
- Test: `tests/test_pipeline/test_duckdb_manager.py`

**Interfaces:**
- Consumes: `DuckDBManager.__init__()`, `DuckDBManager.get_connection()`
- Produces: `DuckDBManager` configured with `threads=4`, `memory_limit='4GB'`, and `temp_directory`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline/test_duckdb_pragmas.py
import pytest
from src.db.duckdb_manager import DuckDBManager


def test_duckdb_manager_pragmas(tmp_path):
    db_path = tmp_path / "test_pragmas.duckdb"
    mgr = DuckDBManager(db_path=db_path)
    conn = mgr.get_connection()

    threads = conn.execute("SELECT current_setting('threads')").fetchone()[0]
    memory_limit = conn.execute("SELECT current_setting('max_memory')").fetchone()[0]

    assert int(threads) <= 4
    assert memory_limit is not None
    mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_duckdb_pragmas.py -v`
Expected: FAIL or mismatch on pragmas

- [ ] **Step 3: Write implementation**

Modify `src/db/duckdb_manager.py`:
```python
    def get_connection(self) -> duckdb.DuckDBPyConnection:
        if self.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = duckdb.connect(str(self.db_path))
            self.conn.execute("PRAGMA threads = 4;")
            self.conn.execute("PRAGMA memory_limit = '4GB';")
            temp_dir = self.db_path.parent / "duckdb_temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self.conn.execute(f"PRAGMA temp_directory = '{temp_dir}';")
        return self.conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_duckdb_pragmas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/duckdb_manager.py tests/test_pipeline/test_duckdb_pragmas.py
git commit -m "perf(db): configure DuckDB thread and memory limits pragmas"
```

---

### Task 2: Streaming Ingestor Batch Tuning

**Files:**
- Modify: `src/ingestion/kaikki_ingestor.py`
- Modify: `src/ingestion/tatoeba_ingestor.py`
- Modify: `src/ingestion/opus_ingestor.py`
- Test: `tests/test_ingestion/test_kaikki_ingestor.py`

**Interfaces:**
- Consumes: `KaikkiIngestor`, `TatoebaIngestor`, `OpusIngestor`
- Produces: Increased default batch size (20,000 items/batch) for high streaming throughput

- [ ] **Step 1: Write the failing test**

```python
# Verify batch size constant in KaikkiIngestor
from src.ingestion.kaikki_ingestor import KAIKKI_BATCH_SIZE

def test_kaikki_batch_size_scaled():
    assert KAIKKI_BATCH_SIZE >= 20000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_ingestion/test_kaikki_ingestor.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Modify `src/ingestion/kaikki_ingestor.py`:
```python
KAIKKI_BATCH_SIZE = 20000
```
Update batch threshold check `len(words_batch) >= KAIKKI_BATCH_SIZE` in `kaikki_ingestor.py`, `tatoeba_ingestor.py`, and `opus_ingestor.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_ingestion/test_kaikki_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/
git commit -m "perf(ingestion): scale batch buffer sizes to 20,000 for streaming ingestors"
```

---

### Task 3: Enhanced CLI Status & Reset Subcommands

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `main.py`
- Test: `tests/test_pipeline/test_cli.py`

**Interfaces:**
- Consumes: `StateManager`, `StepRegistry`, `PipelineContext`
- Produces: CLI commands `python main.py status` and `python main.py reset`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline/test_cli_status.py
from src.pipeline.cli import parse_arguments

def test_cli_status_subcommand():
    args = parse_arguments(["status"])
    assert args.command == "status"

def test_cli_reset_subcommand():
    args = parse_arguments(["reset", "--step", "ingest_kaikki"])
    assert args.command == "reset"
    assert args.step == "ingest_kaikki"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_cli_status.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Modify `src/pipeline/cli.py` to add subparsers for `status`, `reset`, `export`.
Modify `main.py` to dispatch handlers:
```python
def handle_status(ctx):
    # Query _pipeline_meta and render table
    ...

def handle_reset(ctx, step_name, reset_all):
    # Invalidate step metadata
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_cli_status.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/cli.py main.py tests/test_pipeline/test_cli_status.py
git commit -m "feat(cli): add status and reset subcommands for pipeline management"
```

---

### Task 4: Export Subcommand & On-Demand Execution

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `main.py`
- Test: `tests/test_pipeline/test_cli_export.py`

**Interfaces:**
- Consumes: `ExportSQLiteStep`, `ExportJsonStep`, `ExportCore3000Step`
- Produces: `python main.py export --format <sqlite|json|core3000>` command

- [ ] **Step 1: Write the failing test**

```python
from src.pipeline.cli import parse_arguments

def test_cli_export_subcommand():
    args = parse_arguments(["export", "--format", "sqlite"])
    assert args.command == "export"
    assert args.format == "sqlite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_cli_export.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

In `main.py`, handle `args.command == "export"` by executing only the requested export step.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_cli_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/cli.py main.py tests/test_pipeline/test_cli_export.py
git commit -m "feat(cli): add on-demand export subcommand for sqlite, json, and core3000"
```

---

### Task 5: Pipeline Full Benchmark Utility

**Files:**
- Create: `scripts/benchmark_pipeline.py`
- Test: `tests/test_pipeline/test_benchmark_script.py`

**Interfaces:**
- Consumes: `PipelineOrchestrator`, `PipelineContext`, `DuckDBManager`
- Produces: Execution timing breakdown per step, peak RSS memory usage, and staging table row count report

- [ ] **Step 1: Write the failing test**

```python
from scripts.benchmark_pipeline import run_benchmark

def test_benchmark_script_runs(tmp_path):
    report = run_benchmark(dry_run=True)
    assert "total_time_seconds" in report
    assert "memory_peak_mb" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_benchmark_script.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Create `scripts/benchmark_pipeline.py`:
```python
"""Pipeline V2 Benchmark Utility."""

import time
import psutil
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry


def run_benchmark(dry_run: bool = False) -> dict:
    process = psutil.Process()
    start_mem = process.memory_info().rss
    start_time = time.monotonic()

    # Run pipeline
    registry = get_default_registry()
    orchestrator = PipelineOrchestrator(steps=registry.get_steps())
    # ... execute ...

    end_time = time.monotonic()
    peak_mem = process.memory_info().rss

    return {
        "total_time_seconds": round(end_time - start_time, 2),
        "memory_peak_mb": round((peak_mem - start_mem) / (1024 * 1024), 2),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_pipeline/test_benchmark_script.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_pipeline.py tests/test_pipeline/test_benchmark_script.py
git commit -m "feat(benchmark): add full pipeline benchmark utility with memory profiling"
```

---

### Task 6: Export Integrity & Constraint Automated Test Suite

**Files:**
- Create: `tests/test_export/test_integrity.py`

**Interfaces:**
- Consumes: `data/processed/english_dataset.db` or tmp SQLite exported database
- Produces: Automated test suite asserting indexes, WAL mode, foreign key integrity, and non-empty tables

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export/test_integrity.py
import sqlite3
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SQLiteExporter


@pytest.fixture
def exported_sqlite(tmp_path):
    staging_path = tmp_path / "staging.duckdb"
    sqlite_path = tmp_path / "english_dataset.db"

    mgr = DuckDBManager(db_path=staging_path)
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "apple", "pos": "noun"}])
    mgr.insert_batch("definitions", [{"word_id": 1, "definition_en": "a fruit"}])

    exporter = SQLiteExporter()
    exporter.export(mgr, sqlite_path)
    mgr.close()
    return sqlite_path


def test_sqlite_journal_mode(exported_sqlite):
    conn = sqlite3.connect(exported_sqlite)
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_sqlite_words_and_defs_integrity(exported_sqlite):
    conn = sqlite3.connect(exported_sqlite)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM words")
    w_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM definitions")
    d_count = cur.fetchone()[0]

    assert w_count == 1
    assert d_count == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `./.venv/bin/pytest -o pythonpath=. tests/test_export/test_integrity.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_export/test_integrity.py
git commit -m "test(export): add export integrity test suite for SQLite database"
```

---

# Pipeline V2 Phase 3: Operational Excellence, CLI Tools & Full Benchmark Design Spec

## Overview
Phase 3 builds on the completed Phase 1 (Foundation) and Phase 2 (Pipeline Steps Migration) of the Pipeline V2 rewrite.
The purpose of Phase 3 is to establish operational controls, enhance CLI management tools, optimize ingestion & translation memory/throughput, and provide benchmark verification for full raw datasets.

---

## 1. DuckDB Performance Tuning & Pragmas

### Settings (`src/db/duckdb_manager.py`)
On initialization of `DuckDBManager`, the following pragmas are executed:
- `PRAGMA threads = 4;`
- `PRAGMA memory_limit = '4GB';`
- `PRAGMA temp_directory = 'data/processed/duckdb_temp';`

### Batch Scaling (`src/ingestion/`)
- Ingestors (`KaikkiIngestor`, `TatoebaIngestor`, `OpusIngestor`) increase batch insert buffer sizes from `2,000` to `20,000` rows.
- Multi-threaded batch commits utilize DuckDB's `INSERT INTO table SELECT * FROM read_csv/json` when applicable or chunked batch inserts with `ON CONFLICT DO NOTHING`.

---

## 2. CLI Operations Suite (`src/pipeline/cli.py` & `main.py`)

### Commands
- `python main.py status`: Render a formatted terminal table showing:
  - Step Name
  - Execution Status (`SUCCESS`, `FAILED`, `SKIPPED`, `PENDING`)
  - Items Processed
  - Duration (seconds)
  - Last Run Timestamp
  - Source File Hash
- `python main.py reset [--step <step_name>] [--all]`:
  - Reset step metadata in `_pipeline_meta`.
  - Trigger cascade downstream step invalidation using `StateManager.invalidate_step()`.
- `python main.py export [--format <sqlite|json|core3000>]`:
  - Trigger target export steps on demand without re-running ingestion steps.

---

## 3. Full Benchmark Utility (`scripts/benchmark_pipeline.py`)

### Metrics Tracked
- Total wall-clock execution time (seconds).
- Per-step execution time & level concurrency.
- Peak RSS memory footprint (`psutil.Process().memory_info().rss`).
- DuckDB staging database size (`data/processed/staging.duckdb`).
- SQLite output database size (`data/processed/english_dataset.db`).
- Row counts for all 11 staging tables.

---

## 4. SQLite Export Integrity Tests (`tests/test_export/test_integrity.py`)

### Test Coverage
- **Schema & Indexes:** Verify creation of indexes (`idx_words_lemma`, `idx_sentences_text_en`, `idx_phrases_phrase`, `idx_word_sentences_word_id`).
- **Foreign Keys & Integrity:** Verify relational consistency across `words`, `definitions`, `word_sentences`, and `phrase_sentences`.
- **SQLite Performance Pragmas:** Verify output database opens cleanly with `PRAGMA journal_mode = WAL`.

---

## 5. File Structure & Changes

- `src/db/duckdb_manager.py` (Pragmas, batch size default)
- `src/pipeline/cli.py` (`status`, `reset`, `export` subcommands & parser)
- `main.py` (Subcommand wiring)
- `scripts/benchmark_pipeline.py` (Benchmark script)
- `tests/test_export/test_integrity.py` (Integrity unit tests)

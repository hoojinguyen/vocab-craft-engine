# Pipeline V2 Phase 3 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the production-grade SQLite Exporter, Dataset Verifier, and Distribution Packager to transform DuckDB staging tables into an optimized, self-contained, indexed SQLite database (`english_dataset.db`) with SHA256 checksums and zip packaging.

**Architecture:**
- Target SQLite database created with complete mobile/client schema, foreign keys, and covering indexes.
- High-speed export pipeline streaming data from DuckDB staging to SQLite using bulk transaction batching.
- Automated integrity and foreign key verifier (`PRAGMA integrity_check`, `PRAGMA foreign_key_check`, JSON validator).
- Distribution packager generating compressed `.zip` archive, `manifest.json`, and `.sha256` checksum.

**Tech Stack:** Python 3.11+, DuckDB, SQLite3, orjson, hashlib, zipfile, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-pipeline-v2-remediation-spec.md`

## Global Constraints
- SQLite export must complete in **< 60 seconds** on full staging datasets.
- 100% foreign key integrity (`PRAGMA foreign_key_check` returns 0 violations).
- All 11 staging tables must be completely exported into SQLite without dropped columns or mismatched types.
- SQLite database must pass `PRAGMA integrity_check` and include all 14 covering indexes.
- Distribution `.zip` must contain `english_dataset.db` with matching `.sha256` checksum and valid `manifest.json`.

---

### Task 1: SQLite Target Schema & Performance Indexes

**Files:**
- Create/Modify: `src/export/schema.py`
- Test: `tests/test_export/test_export_schema.py`

**Interfaces:**
- Produces: `SQLITE_SCHEMA` DDL string defining all 11 tables, `dataset_metadata` table, and 14 indexes.

- [ ] **Step 1: Write test for SQLite Schema DDL and Indexes**

```python
# tests/test_export/test_export_schema.py
import sqlite3
import pytest
from pathlib import Path
from src.export.schema import SQLITE_SCHEMA, SQLITE_INDEXES, SQLITE_TABLES

def test_sqlite_schema_creates_all_tables_and_indexes(tmp_path: Path):
    db_file = tmp_path / "test_schema.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SQLITE_SCHEMA)
    conn.executescript(SQLITE_INDEXES)

    cursor = conn.cursor()
    tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    
    for expected_table in SQLITE_TABLES:
        assert expected_table in tables

    assert "dataset_metadata" in tables

    indexes = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    assert "idx_words_lemma" in indexes
    assert "idx_definitions_word" in indexes
    assert "idx_word_sentences_word" in indexes
    assert "idx_phrases_phrase" in indexes
    assert "idx_word_topics_word" in indexes
    conn.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_export_schema.py -v`

- [ ] **Step 3: Implement `src/export/schema.py`**

Define:
- `SQLITE_TABLES`: list of 11 core tables + `dataset_metadata`
- `SQLITE_SCHEMA`: DDL for all tables with primary keys, unique constraints, and foreign key references
- `SQLITE_INDEXES`: DDL for all 14 covering indexes for ultra-fast mobile client querying

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_export_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/export/schema.py tests/test_export/test_export_schema.py
git commit -m "feat(export): define comprehensive SQLite target schema and covering indexes"
```

---

### Task 2: High-Performance SQLite Exporter

**Files:**
- Modify: `src/export/sqlite_exporter.py`
- Test: `tests/test_export/test_sqlite_exporter.py`

**Interfaces:**
- Consumes: DuckDB staging database (`DuckDBManager`)
- Produces: Exported SQLite database file (`english_dataset.db`) populated with all records and metadata.

- [ ] **Step 1: Write test for SQLite Exporter**

```python
# tests/test_export/test_sqlite_exporter.py
import sqlite3
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SqliteExporter

def test_sqlite_exporter_full_table_export(tmp_path: Path):
    duckdb_file = tmp_path / "staging.duckdb"
    mgr = DuckDBManager(duckdb_file)
    mgr.init_schema()

    # Populate staging data
    mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "frequency_rank": 50, "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "fast", "pos": "adj", "frequency_rank": 150, "cefr_level": "A1", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("definitions", [
        {"word_id": 1, "definition_en": "to move fast", "definition_vi": "chạy nhanh", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("sentences", [
        {"text_en": "He runs fast.", "text_vi": "Anh ấy chạy nhanh.", "cefr_level": "A1", "source": "tatoeba"},
    ])
    mgr.insert_batch_fast("word_sentences", [{"word_id": 1, "sentence_id": 1}])
    mgr.insert_batch_fast("phrases", [{"phrase": "run out of", "phrase_type": "phrasal_verb", "definition_en": "deplete"}])
    mgr.insert_batch_fast("phrase_sentences", [{"phrase_id": 1, "sentence_id": 1, "rank": 1}])
    mgr.insert_batch_fast("word_topics", [{"word_id": 1, "topic": "Sports", "raw_topic": "sports"}])
    mgr.insert_batch_fast("reflex_drills", [{"sentence_id": 1, "drill_type": "cloze", "prompt_text": "He ___ fast.", "correct_answer": "runs", "distractors_json": '["walks", "jumps", "flies"]', "target_time_ms": 2500}])
    mgr.insert_batch_fast("dialogue_trees", [{"title": "Cafe", "topic": "Food", "cefr_level": "A1"}])
    mgr.insert_batch_fast("dialogue_nodes", [{"tree_id": 1, "speaker_role": "A", "choice_label": "Hello"}])

    sqlite_target = tmp_path / "english_dataset.db"
    exporter = SqliteExporter()
    exported_counts = exporter.export(mgr, sqlite_target)

    assert exported_counts["words"] == 2
    assert exported_counts["definitions"] == 1
    assert exported_counts["sentences"] == 1
    assert exported_counts["word_sentences"] == 1
    assert exported_counts["phrases"] == 1
    assert exported_counts["phrase_sentences"] == 1
    assert exported_counts["word_topics"] == 1
    assert exported_counts["reflex_drills"] == 1
    assert exported_counts["dialogue_trees"] == 1
    assert exported_counts["dialogue_nodes"] == 1

    # Verify SQLite DB
    conn = sqlite3.connect(str(sqlite_target))
    cur = conn.cursor()
    meta = dict(cur.execute("SELECT key, value FROM dataset_metadata").fetchall())
    assert meta["version"] == "2.0"
    assert int(meta["total_words"]) == 2
    assert int(meta["total_sentences"]) == 1
    conn.close()
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_sqlite_exporter.py -v`

- [ ] **Step 3: Implement `SqliteExporter.export`**

Modify `src/export/sqlite_exporter.py`:
- Connect to target SQLite file, initialize schema and temporary fast pragmas (`PRAGMA synchronous = OFF; PRAGMA journal_mode = MEMORY`).
- Stream each table from DuckDB staging in batches of 10,000 using parameterized `executemany`.
- Create all covering indexes after data is inserted.
- Insert `dataset_metadata` table entries (`version`, `created_at`, `total_words`, `total_sentences`, `total_phrases`, `total_reflex_drills`, `total_dialogue_trees`).
- Run `PRAGMA foreign_keys = ON; PRAGMA optimize;`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_sqlite_exporter.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/export/sqlite_exporter.py tests/test_export/test_sqlite_exporter.py
git commit -m "feat(export): implement high-speed streaming SQLite dataset exporter"
```

---

### Task 3: Dataset Integrity Verifier

**Files:**
- Create/Modify: `src/export/verifier.py`
- Test: `tests/test_export/test_verifier.py`

**Interfaces:**
- Consumes: Target SQLite database file (`english_dataset.db`)
- Produces: `VerificationReport` with validation status, table counts, foreign key check results, and JSON validation results.

- [ ] **Step 1: Write test for Dataset Verifier**

```python
# tests/test_export/test_verifier.py
import sqlite3
import pytest
from pathlib import Path
from src.export.schema import SQLITE_SCHEMA, SQLITE_INDEXES
from src.export.verifier import DatasetVerifier, VerificationReport

def test_dataset_verifier_valid_database(tmp_path: Path):
    db_file = tmp_path / "valid.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SQLITE_SCHEMA)
    conn.executescript(SQLITE_INDEXES)

    # Insert sample valid rows
    conn.execute("INSERT INTO words (id, lemma, pos) VALUES (1, 'run', 'verb')")
    conn.execute("INSERT INTO sentences (id, text_en, text_vi) VALUES (1, 'He runs.', 'Anh ấy chạy.')")
    conn.execute("INSERT INTO word_sentences (word_id, sentence_id) VALUES (1, 1)")
    conn.execute("INSERT INTO reflex_drills (id, sentence_id, drill_type, correct_answer, distractors_json) VALUES (1, 1, 'cloze', 'runs', '[\"walks\", \"jumps\", \"flies\"]')")
    conn.execute("INSERT INTO dataset_metadata (key, value) VALUES ('version', '2.0')")
    conn.commit()
    conn.close()

    verifier = DatasetVerifier()
    report: VerificationReport = verifier.verify(db_file)

    assert report.is_valid is True
    assert report.foreign_key_violations == 0
    assert report.integrity_check_passed is True
    assert report.invalid_json_count == 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_verifier.py -v`

- [ ] **Step 3: Implement `DatasetVerifier`**

Implement `src/export/verifier.py`:
- `PRAGMA integrity_check` verification.
- `PRAGMA foreign_key_check` verification.
- Validates all table schemas and column existence.
- Validates `reflex_drills.distractors_json` is valid parseable JSON list.
- Returns comprehensive `VerificationReport(is_valid, table_counts, foreign_key_violations, integrity_check_passed, errors)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_verifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/export/verifier.py tests/test_export/test_verifier.py
git commit -m "feat(export): implement automated dataset verifier with foreign key and JSON validation"
```

---

### Task 4: Distribution Packager & Checksum Generator

**Files:**
- Create/Modify: `src/export/packager.py`
- Test: `tests/test_export/test_packager.py`

**Interfaces:**
- Consumes: Target SQLite database file (`english_dataset.db`)
- Produces: `english_dataset.zip`, `english_dataset.db.sha256`, and `manifest.json`.

- [ ] **Step 1: Write test for Packager**

```python
# tests/test_export/test_packager.py
import json
import pytest
from pathlib import Path
from src.export.packager import DatasetPackager

def test_dataset_packager_creates_zip_and_checksum(tmp_path: Path):
    db_file = tmp_path / "english_dataset.db"
    db_file.write_bytes(b"SQLite format 3\x00dummy data for packaging test")

    output_dir = tmp_path / "dist"
    packager = DatasetPackager()
    result = packager.package(db_file, output_dir=output_dir, version="2.0.0")

    assert result["zip_path"].exists()
    assert result["sha256_path"].exists()
    assert result["manifest_path"].exists()

    # Verify sha256
    sha_content = result["sha256_path"].read_text().strip()
    assert len(sha_content.split()[0]) == 64

    # Verify manifest
    manifest = json.loads(result["manifest_path"].read_text())
    assert manifest["version"] == "2.0.0"
    assert "file_size_bytes" in manifest
    assert "sha256" in manifest
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_packager.py -v`

- [ ] **Step 3: Implement `DatasetPackager`**

Implement `src/export/packager.py`:
- Calculates SHA256 checksum of `english_dataset.db`.
- Writes `.sha256` checksum file.
- Generates `manifest.json` with file stats, version, timestamps, and checksum.
- Compresses `english_dataset.db` into `english_dataset.zip` using `zipfile.ZIP_DEFLATED`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/test_packager.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/export/packager.py tests/test_export/test_packager.py
git commit -m "feat(export): implement distribution packager with SHA256 checksum and manifest"
```

---

### Task 5: Step Wrappers & Full Phase 3 End-to-End Verification

**Files:**
- Modify: `src/pipeline/steps/export_sqlite.py`
- Modify: `src/pipeline/steps/export_package.py`
- Test: `tests/test_export/test_phase3_verification.py`

**Interfaces:**
- Consumes: PipelineContext with DuckDB staging database
- Produces: Complete exported SQLite dataset and verified distribution package.

- [ ] **Step 1: Update step wrappers in `src/pipeline/steps/`**

Wire `SqliteExporter`, `DatasetVerifier`, and `DatasetPackager` into:
- `export_sqlite.py`: calls `SqliteExporter.export` and `DatasetVerifier.verify`
- `export_package.py`: calls `DatasetPackager.package`

- [ ] **Step 2: Write comprehensive Phase 3 E2E test**

Create `tests/test_export/test_phase3_verification.py` running the complete pipeline from staging through SQLite export, verification, and packaging.

- [ ] **Step 3: Run all export tests**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_export/ -v`
Expected: All tests pass.

- [ ] **Step 4: Run full project regression test suite**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_ingestion/ tests/test_transform/ tests/test_enrichment/ tests/test_export/ tests/test_pipeline/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit changes**

```bash
git add src/pipeline/steps/export_sqlite.py src/pipeline/steps/export_package.py tests/test_export/
git commit -m "feat(pipeline): complete Phase 3 Core Dataset Exporter and SQLite packaging overhaul"
```

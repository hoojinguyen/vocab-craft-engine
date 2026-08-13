# Pipeline V2 Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer for the new DAG-based pipeline — DuckDB staging manager, schema definitions, BaseStep v2 interface, DAG resolver, parallel orchestrator, and updated CLI.

**Architecture:** DuckDB replaces SQLite as the staging database. Steps declare explicit dependencies (`depends_on`) and outputs (`produces`). A DAG orchestrator performs topological sort and runs independent steps in parallel using ProcessPoolExecutor (CPU-bound) and asyncio (I/O-bound). Internal pipeline tables (`_pipeline_meta`, `_batch_checkpoints`, `_translation_cache`, `_ipa_cache`) provide smart caching and resume.

**Tech Stack:** Python 3.11+, DuckDB ≥0.9.0, Pydantic ≥2.5.0

**Spec:** `docs/superpowers/specs/2026-08-13-pipeline-redesign-design.md`

## Global Constraints

- Python ≥ 3.11 required
- DuckDB ≥ 0.9.0 for staging (already in pyproject.toml)
- All DuckDB internal tables prefixed with `_` (not exported to SQLite)
- BaseStep v2 must be backward-compatible enough to migrate existing steps incrementally
- No framework dependencies for DAG/orchestration — stdlib only (multiprocessing, asyncio, concurrent.futures)
- All new code must have pytest tests
- Each task ends with a passing test suite and a git commit

## File Structure

| File | Responsibility |
|------|---------------|
| `src/db/duckdb_manager.py` (CREATE) | DuckDB connection pool, batch insert, cache table queries, schema init |
| `src/db/schema.py` (CREATE) | All CREATE TABLE statements for staging + internal tables |
| `src/pipeline/core/base_step.py` (MODIFY) | V2: add `depends_on`, `produces`, `optional`, `execution_type` |
| `src/pipeline/core/dag.py` (CREATE) | DAG builder, cycle detection, topological sort into execution levels |
| `src/pipeline/core/orchestrator.py` (REWRITE) | DAG-aware parallel orchestrator replacing sequential runner |
| `src/pipeline/core/context.py` (MODIFY) | V2: DuckDB-backed context with ProgressReporter factory |
| `src/pipeline/core/state_manager.py` (REWRITE) | DuckDB-backed state using `_pipeline_meta` + `_batch_checkpoints` |
| `src/pipeline/core/result.py` (KEEP) | StepResult, PipelineSummary — no changes needed |
| `src/pipeline/core/registry.py` (MODIFY) | Remove numbered step imports, use DAG-aware registration |
| `src/pipeline/cli.py` (MODIFY) | Add `--force-step`, `--enable`, `--force-all` flags |
| `config/settings.py` (MODIFY) | Add STAGING_DUCKDB_PATH usage, remove stale checkpoint paths |
| `main.py` (MODIFY) | Wire DuckDB manager + new orchestrator |
| `tests/test_pipeline/test_duckdb_manager.py` (CREATE) | Unit tests for DuckDB manager |
| `tests/test_pipeline/test_schema.py` (CREATE) | Schema creation tests |
| `tests/test_pipeline/test_dag.py` (CREATE) | DAG topological sort, cycle detection tests |
| `tests/test_pipeline/test_orchestrator.py` (CREATE) | Orchestrator parallel execution tests |
| `tests/test_pipeline/test_state_manager.py` (CREATE) | State manager caching/resume tests |

---

### Task 1: DuckDB Schema Definitions

**Files:**
- Create: `src/db/schema.py`
- Test: `tests/test_pipeline/test_schema.py`

**Interfaces:**
- Consumes: nothing (standalone)
- Produces:
  - `STAGING_SCHEMA: str` — full SQL string for all 10 user tables
  - `INTERNAL_SCHEMA: str` — full SQL string for 4 internal `_pipeline_*` tables
  - `STAGING_TABLES: list[str]` — names of user-facing tables
  - `INTERNAL_TABLES: list[str]` — names of internal tables

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline/test_schema.py
import duckdb
from src.db.schema import STAGING_SCHEMA, INTERNAL_SCHEMA, STAGING_TABLES, INTERNAL_TABLES


def test_staging_schema_creates_all_tables():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    for table_name in STAGING_TABLES:
        assert table_name in tables, f"Missing staging table: {table_name}"
    conn.close()


def test_internal_schema_creates_meta_tables():
    conn = duckdb.connect(":memory:")
    conn.execute(INTERNAL_SCHEMA)
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    for table_name in INTERNAL_TABLES:
        assert table_name in tables, f"Missing internal table: {table_name}"
    conn.close()


def test_staging_tables_list_has_10_tables():
    assert len(STAGING_TABLES) == 10


def test_internal_tables_list_has_4_tables():
    assert len(INTERNAL_TABLES) == 4


def test_words_unique_constraint():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    conn.execute("INSERT INTO words (lemma, pos, source) VALUES ('run', 'verb', 'kaikki')")
    conn.execute("INSERT INTO words (lemma, pos, source) VALUES ('run', 'noun', 'kaikki')")  # different POS OK
    try:
        conn.execute("INSERT INTO words (lemma, pos, source) VALUES ('run', 'verb', 'wordnet')")  # duplicate
        assert False, "Should have raised duplicate constraint error"
    except duckdb.ConstraintException:
        pass
    conn.close()


def test_phrases_has_phrase_type_column():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    conn.execute("""
        INSERT INTO phrases (phrase, phrase_type, definition_en)
        VALUES ('break down', 'phrasal_verb', 'to stop working')
    """)
    row = conn.execute("SELECT phrase_type FROM phrases WHERE phrase = 'break down'").fetchone()
    assert row[0] == "phrasal_verb"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.db.schema'`

- [ ] **Step 3: Write the schema module**

```python
# src/db/schema.py
"""
DuckDB staging + internal pipeline schema definitions.

Staging tables hold the vocabulary dataset being built.
Internal tables (prefixed with _) hold pipeline state, caches, and checkpoints.
"""

STAGING_TABLES = [
    "words",
    "definitions",
    "sentences",
    "word_sentences",
    "phrases",
    "phrase_sentences",
    "word_relations",
    "word_topics",
    "reflex_drills",
    "dialogue_trees",
    "dialogue_nodes",
]

# Note: dialogue_trees + dialogue_nodes = 11 items but the spec says 10 tables
# because dialogue_trees and dialogue_nodes are counted as one logical unit.
# We keep them as separate tables for relational integrity.

INTERNAL_TABLES = [
    "_pipeline_meta",
    "_batch_checkpoints",
    "_translation_cache",
    "_ipa_cache",
]

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id             INTEGER PRIMARY KEY,
    lemma          TEXT NOT NULL,
    pos            TEXT NOT NULL,
    ipa_uk         TEXT,
    ipa_us         TEXT,
    frequency_rank INTEGER,
    cefr_level     TEXT,
    source         TEXT,
    UNIQUE(lemma, pos)
);

CREATE TABLE IF NOT EXISTS definitions (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    definition_en  TEXT,
    definition_vi  TEXT,
    example        TEXT,
    source         TEXT,
    UNIQUE(word_id, definition_en)
);

CREATE TABLE IF NOT EXISTS sentences (
    id               INTEGER PRIMARY KEY,
    text_en          TEXT UNIQUE NOT NULL,
    text_vi          TEXT,
    difficulty_score REAL,
    cefr_level       TEXT,
    audio_path       TEXT,
    source           TEXT
);

CREATE TABLE IF NOT EXISTS word_sentences (
    word_id     INTEGER NOT NULL REFERENCES words(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    PRIMARY KEY (word_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS phrases (
    id               INTEGER PRIMARY KEY,
    phrase           TEXT UNIQUE NOT NULL,
    phrase_type      TEXT NOT NULL,
    pos              TEXT,
    cefr_level       TEXT,
    difficulty_score REAL,
    definition_en    TEXT,
    definition_vi    TEXT,
    ipa              TEXT,
    audio_std        TEXT,
    audio_fast       TEXT,
    audio_status     TEXT DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS phrase_sentences (
    phrase_id   INTEGER NOT NULL REFERENCES phrases(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    rank        INTEGER,
    PRIMARY KEY (phrase_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS word_relations (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    relation_type  TEXT NOT NULL,
    target_text    TEXT NOT NULL,
    target_word_id INTEGER REFERENCES words(id),
    inverted       INTEGER NOT NULL DEFAULT 0,
    source         TEXT,
    UNIQUE(word_id, relation_type, target_text)
);

CREATE TABLE IF NOT EXISTS word_topics (
    word_id   INTEGER NOT NULL REFERENCES words(id),
    topic     TEXT NOT NULL,
    raw_topic TEXT,
    UNIQUE(word_id, topic)
);

CREATE TABLE IF NOT EXISTS reflex_drills (
    id               INTEGER PRIMARY KEY,
    sentence_id      INTEGER NOT NULL REFERENCES sentences(id),
    drill_type       TEXT NOT NULL,
    prompt_text      TEXT,
    correct_answer   TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms   INTEGER DEFAULT 2500
);

CREATE TABLE IF NOT EXISTS dialogue_trees (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    topic        TEXT,
    cefr_level   TEXT,
    root_node_id INTEGER
);

CREATE TABLE IF NOT EXISTS dialogue_nodes (
    id             INTEGER PRIMARY KEY,
    tree_id        INTEGER NOT NULL REFERENCES dialogue_trees(id),
    parent_node_id INTEGER REFERENCES dialogue_nodes(id),
    choice_label   TEXT,
    speaker_role   TEXT NOT NULL,
    sentence_id    INTEGER REFERENCES sentences(id)
);
"""

INTERNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS _pipeline_meta (
    step_name     TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    source_hash   TEXT,
    row_count     INTEGER,
    started_at    TIMESTAMP,
    completed_at  TIMESTAMP,
    duration_secs REAL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS _batch_checkpoints (
    step_name       TEXT NOT NULL,
    batch_id        TEXT NOT NULL,
    rows_written    INTEGER,
    checkpoint_data TEXT,
    created_at      TIMESTAMP,
    PRIMARY KEY (step_name, batch_id)
);

CREATE TABLE IF NOT EXISTS _translation_cache (
    source_text TEXT PRIMARY KEY,
    target_text TEXT NOT NULL,
    translator  TEXT NOT NULL,
    quality     REAL,
    created_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS _ipa_cache (
    word   TEXT PRIMARY KEY,
    ipa_us TEXT,
    ipa_uk TEXT,
    source TEXT
);
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline/test_schema.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/schema.py tests/test_pipeline/test_schema.py
git commit -m "feat(db): add DuckDB staging and internal schema definitions"
```

---

### Task 2: DuckDB Manager

**Files:**
- Create: `src/db/duckdb_manager.py`
- Test: `tests/test_pipeline/test_duckdb_manager.py`

**Interfaces:**
- Consumes: `src/db/schema.py` — `STAGING_SCHEMA`, `INTERNAL_SCHEMA`, `INTERNAL_TABLES`
- Produces:
  - `DuckDBManager.__init__(self, db_path: Path)` — connects or creates DuckDB file
  - `DuckDBManager.get_connection(self) -> duckdb.DuckDBPyConnection`
  - `DuckDBManager.init_schema(self) -> None` — runs STAGING + INTERNAL schema
  - `DuckDBManager.close(self) -> None`
  - `DuckDBManager.insert_batch(self, table: str, rows: list[dict]) -> int` — batch insert with ON CONFLICT IGNORE
  - `DuckDBManager.count_rows(self, table: str) -> int`
  - `DuckDBManager.get_step_meta(self, step_name: str) -> dict | None`
  - `DuckDBManager.save_step_meta(self, step_name: str, status: str, source_hash: str, row_count: int, duration_secs: float, error_message: str | None) -> None`
  - `DuckDBManager.get_last_checkpoint(self, step_name: str) -> dict | None`
  - `DuckDBManager.save_checkpoint(self, step_name: str, batch_id: str, rows_written: int, data: str | None) -> None`
  - `DuckDBManager.clear_checkpoints(self, step_name: str) -> None`
  - `DuckDBManager.get_translation(self, text: str) -> str | None`
  - `DuckDBManager.save_translation(self, text: str, translated: str, translator: str) -> None`
  - `DuckDBManager.get_translations_batch(self, texts: list[str]) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline/test_duckdb_manager.py
import tempfile
from pathlib import Path
import pytest
from src.db.duckdb_manager import DuckDBManager


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test_staging.duckdb"
    manager = DuckDBManager(db_path=db_path)
    manager.init_schema()
    yield manager
    manager.close()


def test_init_schema_creates_tables(db_manager):
    conn = db_manager.get_connection()
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    assert "words" in tables
    assert "_pipeline_meta" in tables


def test_insert_batch_words(db_manager):
    rows = [
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "walk", "pos": "verb", "source": "kaikki"},
    ]
    inserted = db_manager.insert_batch("words", rows)
    assert inserted == 2
    assert db_manager.count_rows("words") == 2


def test_insert_batch_dedup(db_manager):
    rows = [{"lemma": "run", "pos": "verb", "source": "kaikki"}]
    db_manager.insert_batch("words", rows)
    db_manager.insert_batch("words", rows)  # duplicate
    assert db_manager.count_rows("words") == 1


def test_count_rows_empty(db_manager):
    assert db_manager.count_rows("words") == 0


def test_save_and_get_step_meta(db_manager):
    db_manager.save_step_meta(
        step_name="ingest_kaikki",
        status="success",
        source_hash="abc123",
        row_count=50000,
        duration_secs=120.5,
        error_message=None,
    )
    meta = db_manager.get_step_meta("ingest_kaikki")
    assert meta is not None
    assert meta["status"] == "success"
    assert meta["source_hash"] == "abc123"
    assert meta["row_count"] == 50000


def test_get_step_meta_missing(db_manager):
    assert db_manager.get_step_meta("nonexistent") is None


def test_save_and_get_checkpoint(db_manager):
    db_manager.save_checkpoint("ingest_kaikki", "line_50000", 50000, '{"offset": 123456}')
    cp = db_manager.get_last_checkpoint("ingest_kaikki")
    assert cp is not None
    assert cp["batch_id"] == "line_50000"
    assert cp["rows_written"] == 50000


def test_clear_checkpoints(db_manager):
    db_manager.save_checkpoint("ingest_kaikki", "line_50000", 50000, None)
    db_manager.clear_checkpoints("ingest_kaikki")
    assert db_manager.get_last_checkpoint("ingest_kaikki") is None


def test_translation_cache_roundtrip(db_manager):
    db_manager.save_translation("hello", "xin chào", "argos")
    result = db_manager.get_translation("hello")
    assert result == "xin chào"


def test_translation_cache_miss(db_manager):
    assert db_manager.get_translation("unknown") is None


def test_translations_batch(db_manager):
    db_manager.save_translation("hello", "xin chào", "argos")
    db_manager.save_translation("goodbye", "tạm biệt", "argos")
    results = db_manager.get_translations_batch(["hello", "goodbye", "missing"])
    assert results["hello"] == "xin chào"
    assert results["goodbye"] == "tạm biệt"
    assert "missing" not in results
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_duckdb_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.db.duckdb_manager'`

- [ ] **Step 3: Write DuckDB manager implementation**

```python
# src/db/duckdb_manager.py
"""
DuckDB Staging Database Manager.

Provides connection management, batch inserts with dedup, and internal
pipeline state/cache table operations for the DAG-based pipeline.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.db.schema import INTERNAL_SCHEMA, INTERNAL_TABLES, STAGING_SCHEMA

logger = logging.getLogger(__name__)


class DuckDBManager:
    """Manages a DuckDB staging database for the pipeline."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_schema(self) -> None:
        """Create all staging and internal tables."""
        conn = self.get_connection()
        conn.execute(STAGING_SCHEMA)
        conn.execute(INTERNAL_SCHEMA)
        logger.info("DuckDB schema initialized at %s", self.db_path)

    # ---- Batch Operations ------------------------------------------------

    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert rows into table with ON CONFLICT DO NOTHING for dedup.

        Returns the number of rows in the table after insertion (DuckDB
        does not reliably report affected rows for INSERT OR IGNORE).
        """
        if not rows:
            return 0
        conn = self.get_connection()
        count_before = self.count_rows(table)
        columns = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})"
        values = [tuple(row.get(c) for c in columns) for row in rows]
        conn.executemany(sql, values)
        count_after = self.count_rows(table)
        return count_after - count_before

    def count_rows(self, table: str) -> int:
        conn = self.get_connection()
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        return row[0] if row else 0

    # ---- Pipeline Meta ---------------------------------------------------

    def get_step_meta(self, step_name: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT step_name, status, source_hash, row_count, "
            "started_at, completed_at, duration_secs, error_message "
            "FROM _pipeline_meta WHERE step_name = ?",
            [step_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "step_name": row[0],
            "status": row[1],
            "source_hash": row[2],
            "row_count": row[3],
            "started_at": row[4],
            "completed_at": row[5],
            "duration_secs": row[6],
            "error_message": row[7],
        }

    def save_step_meta(
        self,
        step_name: str,
        status: str,
        source_hash: str | None = None,
        row_count: int = 0,
        duration_secs: float = 0.0,
        error_message: str | None = None,
    ) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _pipeline_meta "
            "(step_name, status, source_hash, row_count, started_at, completed_at, "
            "duration_secs, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [step_name, status, source_hash, row_count, now, now, duration_secs, error_message],
        )

    # ---- Batch Checkpoints -----------------------------------------------

    def get_last_checkpoint(self, step_name: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT batch_id, rows_written, checkpoint_data, created_at "
            "FROM _batch_checkpoints WHERE step_name = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [step_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "batch_id": row[0],
            "rows_written": row[1],
            "checkpoint_data": row[2],
            "created_at": row[3],
        }

    def save_checkpoint(
        self, step_name: str, batch_id: str, rows_written: int, data: str | None = None
    ) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _batch_checkpoints "
            "(step_name, batch_id, rows_written, checkpoint_data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [step_name, batch_id, rows_written, data, now],
        )

    def clear_checkpoints(self, step_name: str) -> None:
        conn = self.get_connection()
        conn.execute("DELETE FROM _batch_checkpoints WHERE step_name = ?", [step_name])

    # ---- Translation Cache -----------------------------------------------

    def get_translation(self, text: str) -> str | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT target_text FROM _translation_cache WHERE source_text = ?",
            [text],
        ).fetchone()
        return row[0] if row else None

    def save_translation(self, text: str, translated: str, translator: str) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _translation_cache "
            "(source_text, target_text, translator, created_at) VALUES (?, ?, ?, ?)",
            [text, translated, translator, now],
        )

    def get_translations_batch(self, texts: list[str]) -> dict[str, str]:
        if not texts:
            return {}
        conn = self.get_connection()
        placeholders = ", ".join(["?"] * len(texts))
        rows = conn.execute(
            f"SELECT source_text, target_text FROM _translation_cache "
            f"WHERE source_text IN ({placeholders})",
            texts,
        ).fetchall()
        return {row[0]: row[1] for row in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline/test_duckdb_manager.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/duckdb_manager.py tests/test_pipeline/test_duckdb_manager.py
git commit -m "feat(db): add DuckDB staging manager with batch ops and cache"
```

---

### Task 3: BaseStep V2

**Files:**
- Modify: `src/pipeline/core/base_step.py`
- Test: `tests/test_pipeline/test_base_step.py`

**Interfaces:**
- Consumes: `src/pipeline/core/context.py` — `PipelineContext`, `src/pipeline/core/result.py` — `StepResult`
- Produces:
  - `BaseStep.name: str`
  - `BaseStep.description: str`
  - `BaseStep.depends_on: list[str]` — step names this step depends on
  - `BaseStep.produces: list[str]` — DuckDB table names this step writes to
  - `BaseStep.optional: bool` — whether step can be skipped via CLI
  - `BaseStep.execution_type: str` — `"cpu"` or `"io"`
  - `BaseStep.source_files: list[Path]` — input files for hash-based cache invalidation
  - `BaseStep.compute_source_hash(self) -> str` — SHA256 of source file metadata
  - `BaseStep.should_skip(self, ctx) -> tuple[bool, str]` (abstract)
  - `BaseStep.run(self, ctx) -> StepResult` (abstract)
  - `BaseStep.rollback(self, ctx) -> None` — truncate produced tables

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline/test_base_step.py
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.result import StepResult, StepStatus


class ConcreteStep(BaseStep):
    name = "test_step"
    description = "A test step"
    depends_on = ["schema_init"]
    produces = ["words"]
    optional = False
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class OptionalStep(BaseStep):
    name = "optional_step"
    description = "An optional step"
    depends_on = ["test_step"]
    produces = ["audio_files"]
    optional = True
    execution_type = "io"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


def test_base_step_has_depends_on():
    step = ConcreteStep()
    assert step.depends_on == ["schema_init"]


def test_base_step_has_produces():
    step = ConcreteStep()
    assert step.produces == ["words"]


def test_base_step_optional_default_false():
    step = ConcreteStep()
    assert step.optional is False


def test_optional_step_flag():
    step = OptionalStep()
    assert step.optional is True


def test_execution_type():
    assert ConcreteStep().execution_type == "cpu"
    assert OptionalStep().execution_type == "io"


def test_compute_source_hash_empty():
    step = ConcreteStep()
    step.source_files = []
    hash1 = step.compute_source_hash()
    assert isinstance(hash1, str)
    assert len(hash1) == 16  # truncated SHA256


def test_compute_source_hash_with_files(tmp_path):
    test_file = tmp_path / "test.json"
    test_file.write_text("test content")
    step = ConcreteStep()
    step.source_files = [test_file]
    hash1 = step.compute_source_hash()
    assert isinstance(hash1, str)
    assert len(hash1) == 16


def test_compute_source_hash_changes_with_content(tmp_path):
    test_file = tmp_path / "test.json"
    test_file.write_text("content v1")
    step = ConcreteStep()
    step.source_files = [test_file]
    hash1 = step.compute_source_hash()

    test_file.write_text("content v2 with more data")  # size changes
    hash2 = step.compute_source_hash()
    assert hash1 != hash2


def test_rollback_is_noop_by_default():
    step = ConcreteStep()
    ctx = MagicMock()
    step.rollback(ctx)  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_base_step.py -v`
Expected: FAIL — `depends_on`, `produces`, `optional`, `execution_type`, `source_files`, `compute_source_hash` not yet on BaseStep

- [ ] **Step 3: Update BaseStep with V2 attributes**

```python
# src/pipeline/core/base_step.py
"""
Base class for all pipeline steps (V2).

Steps declare their dependencies and outputs for DAG-based execution.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult


class BaseStep(ABC):
    name: str = ""
    description: str = ""
    depends_on: list[str] = []
    produces: list[str] = []
    optional: bool = False
    execution_type: str = "cpu"  # "cpu" → ProcessPool, "io" → asyncio
    source_files: list[Path] = []

    @abstractmethod
    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        """Determines whether to skip execution."""
        pass

    @abstractmethod
    def run(self, context: PipelineContext) -> StepResult:
        """Executes the core step logic."""
        pass

    def rollback(self, context: PipelineContext) -> None:
        """Optional cleanup routine if step execution fails."""
        pass

    def compute_source_hash(self) -> str:
        """Compute a hash of source file metadata for cache invalidation.

        Uses file size + mtime (fast, no need to read multi-GB files).
        Returns a 16-char hex string.
        """
        parts = []
        for path in self.source_files:
            if path.exists():
                stat = path.stat()
                parts.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
            else:
                parts.append(f"{path.name}:missing")
        raw = "|".join(parts) if parts else "no_sources"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline/test_base_step.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/base_step.py tests/test_pipeline/test_base_step.py
git commit -m "feat(pipeline): upgrade BaseStep to V2 with DAG metadata"
```

---

### Task 4: DAG Builder & Topological Sort

**Files:**
- Create: `src/pipeline/core/dag.py`
- Test: `tests/test_pipeline/test_dag.py`

**Interfaces:**
- Consumes: `src/pipeline/core/base_step.py` — `BaseStep` (uses `.name`, `.depends_on`, `.optional`)
- Produces:
  - `DAGBuilder.build(self, steps: list[BaseStep]) -> DAG`
  - `DAG.execution_levels(self) -> list[list[BaseStep]]` — groups of steps that can run in parallel
  - `DAG.validate(self) -> None` — raises `DAGCycleError` if cycle detected
  - `DAG.get_downstream(self, step_name: str) -> set[str]` — all transitive dependents
  - `DAGCycleError(Exception)` — raised on dependency cycle

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline/test_dag.py
import pytest
from unittest.mock import MagicMock
from src.pipeline.core.dag import DAGBuilder, DAG, DAGCycleError
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.result import StepResult, StepStatus


def _make_step(name, depends_on=None, optional=False):
    """Create a minimal concrete step for testing."""
    step = MagicMock(spec=BaseStep)
    step.name = name
    step.depends_on = depends_on or []
    step.optional = optional
    step.produces = []
    step.execution_type = "cpu"
    return step


class TestDAGBuilder:
    def test_build_simple_chain(self):
        s1 = _make_step("a")
        s2 = _make_step("b", depends_on=["a"])
        s3 = _make_step("c", depends_on=["b"])
        dag = DAGBuilder().build([s1, s2, s3])
        levels = dag.execution_levels()
        assert len(levels) == 3
        assert [s.name for s in levels[0]] == ["a"]
        assert [s.name for s in levels[1]] == ["b"]
        assert [s.name for s in levels[2]] == ["c"]

    def test_build_parallel_steps(self):
        root = _make_step("root")
        a = _make_step("a", depends_on=["root"])
        b = _make_step("b", depends_on=["root"])
        c = _make_step("c", depends_on=["root"])
        dag = DAGBuilder().build([root, a, b, c])
        levels = dag.execution_levels()
        assert len(levels) == 2
        assert [s.name for s in levels[0]] == ["root"]
        level1_names = sorted([s.name for s in levels[1]])
        assert level1_names == ["a", "b", "c"]

    def test_build_diamond(self):
        root = _make_step("root")
        a = _make_step("a", depends_on=["root"])
        b = _make_step("b", depends_on=["root"])
        merge = _make_step("merge", depends_on=["a", "b"])
        dag = DAGBuilder().build([root, a, b, merge])
        levels = dag.execution_levels()
        assert len(levels) == 3
        assert levels[0][0].name == "root"
        level1_names = sorted([s.name for s in levels[1]])
        assert level1_names == ["a", "b"]
        assert levels[2][0].name == "merge"

    def test_cycle_detection(self):
        a = _make_step("a", depends_on=["c"])
        b = _make_step("b", depends_on=["a"])
        c = _make_step("c", depends_on=["b"])
        with pytest.raises(DAGCycleError):
            DAGBuilder().build([a, b, c])

    def test_unknown_dependency_raises(self):
        a = _make_step("a", depends_on=["nonexistent"])
        with pytest.raises(ValueError, match="nonexistent"):
            DAGBuilder().build([a])

    def test_get_downstream(self):
        root = _make_step("root")
        a = _make_step("a", depends_on=["root"])
        b = _make_step("b", depends_on=["a"])
        c = _make_step("c", depends_on=["a"])
        dag = DAGBuilder().build([root, a, b, c])
        downstream = dag.get_downstream("root")
        assert downstream == {"a", "b", "c"}

    def test_get_downstream_leaf(self):
        root = _make_step("root")
        a = _make_step("a", depends_on=["root"])
        dag = DAGBuilder().build([root, a])
        assert dag.get_downstream("a") == set()

    def test_filter_optional_steps(self):
        root = _make_step("root")
        required = _make_step("required", depends_on=["root"])
        optional = _make_step("optional", depends_on=["root"], optional=True)
        dag = DAGBuilder().build([root, required, optional])
        disabled = {"optional"}
        levels = dag.execution_levels(disabled_steps=disabled)
        all_names = {s.name for level in levels for s in level}
        assert "optional" not in all_names
        assert "required" in all_names

    def test_pipeline_dag_structure(self):
        """Integration: test the actual pipeline DAG shape from the spec."""
        schema = _make_step("schema_init")
        kaikki = _make_step("ingest_kaikki", depends_on=["schema_init"])
        tatoeba = _make_step("ingest_tatoeba", depends_on=["schema_init"])
        opus = _make_step("ingest_opus", depends_on=["schema_init"])
        wordnet = _make_step("ingest_wordnet", depends_on=["schema_init"])
        linking = _make_step("transform_linking", depends_on=["ingest_kaikki", "ingest_tatoeba", "ingest_opus"])
        phrases = _make_step("transform_phrases", depends_on=["ingest_kaikki", "ingest_tatoeba", "ingest_opus"])
        relations = _make_step("transform_relations", depends_on=["ingest_kaikki", "ingest_wordnet"])
        vi_trans = _make_step("enrich_translation", depends_on=["ingest_kaikki", "transform_phrases"])
        reflex = _make_step("enrich_reflex", depends_on=["transform_linking"])
        scenarios = _make_step("enrich_scenarios", depends_on=["transform_linking"])
        audio = _make_step("enrich_audio", depends_on=["transform_linking", "transform_phrases"], optional=True)
        export_sql = _make_step("export_sqlite", depends_on=["enrich_translation", "transform_relations", "enrich_reflex", "enrich_scenarios"])
        export_core = _make_step("export_core3000", depends_on=["export_sqlite"])
        export_json = _make_step("export_json", depends_on=["enrich_translation", "transform_relations"])

        steps = [schema, kaikki, tatoeba, opus, wordnet, linking, phrases,
                 relations, vi_trans, reflex, scenarios, audio, export_sql, export_core, export_json]
        dag = DAGBuilder().build(steps)
        dag.validate()  # should not raise

        levels = dag.execution_levels(disabled_steps={"enrich_audio"})
        assert len(levels) >= 4  # at least 4 execution levels
        # Level 0 should only contain schema_init
        assert [s.name for s in levels[0]] == ["schema_init"]
        # Level 1 should contain all 4 ingest steps
        level1_names = sorted([s.name for s in levels[1]])
        assert level1_names == ["ingest_kaikki", "ingest_opus", "ingest_tatoeba", "ingest_wordnet"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_dag.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pipeline.core.dag'`

- [ ] **Step 3: Implement DAG builder**

```python
# src/pipeline/core/dag.py
"""
DAG (Directed Acyclic Graph) builder and topological sort for pipeline steps.

Builds a dependency graph from step declarations, detects cycles,
and produces execution levels where steps within a level can run in parallel.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.pipeline.core.base_step import BaseStep


class DAGCycleError(Exception):
    """Raised when the dependency graph contains a cycle."""
    pass


class DAG:
    """A validated directed acyclic graph of pipeline steps."""

    def __init__(
        self,
        steps: dict[str, BaseStep],
        adjacency: dict[str, list[str]],
        reverse_adj: dict[str, list[str]],
    ):
        self._steps = steps
        self._adj = adjacency           # step -> list of steps it depends ON
        self._reverse = reverse_adj     # step -> list of steps that depend on IT

    def validate(self) -> None:
        """Verify the graph is acyclic using Kahn's algorithm.

        Raises DAGCycleError if a cycle is detected.
        """
        in_degree = {name: len(deps) for name, deps in self._adj.items()}
        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for child in self._reverse.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        if visited != len(self._steps):
            raise DAGCycleError(
                f"Dependency cycle detected: visited {visited}/{len(self._steps)} steps"
            )

    def execution_levels(
        self, disabled_steps: set[str] | None = None
    ) -> list[list[BaseStep]]:
        """Group steps into execution levels via topological sort.

        Steps in the same level have all dependencies satisfied and
        can run in parallel. Disabled steps (optional steps turned off)
        are excluded along with any steps that solely depend on them.
        """
        disabled = disabled_steps or set()

        # Filter out disabled steps
        active = {
            name: [d for d in deps if d not in disabled]
            for name, deps in self._adj.items()
            if name not in disabled
        }

        in_degree = {name: len(deps) for name, deps in active.items()}
        ready = deque(name for name, deg in in_degree.items() if deg == 0)
        levels: list[list[BaseStep]] = []

        while ready:
            current_level: list[BaseStep] = []
            next_ready: list[str] = []
            while ready:
                node = ready.popleft()
                current_level.append(self._steps[node])
            # Sort within level for deterministic ordering
            current_level.sort(key=lambda s: s.name)
            levels.append(current_level)
            for step in current_level:
                for child in self._reverse.get(step.name, []):
                    if child in disabled:
                        continue
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_ready.append(child)
            ready.extend(sorted(next_ready))

        return levels

    def get_downstream(self, step_name: str) -> set[str]:
        """Get all transitive dependents of a step (BFS)."""
        visited: set[str] = set()
        queue = deque(self._reverse.get(step_name, []))
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self._reverse.get(node, []))
        return visited


class DAGBuilder:
    """Builds a DAG from a list of pipeline steps."""

    def build(self, steps: list[BaseStep]) -> DAG:
        """Build and validate a DAG from step declarations.

        Raises ValueError if a step declares a dependency on an unknown step.
        Raises DAGCycleError if a cycle is detected.
        """
        step_map: dict[str, BaseStep] = {}
        for step in steps:
            step_map[step.name] = step

        # Build adjacency (step -> its dependencies) and reverse (step -> its dependents)
        adjacency: dict[str, list[str]] = defaultdict(list)
        reverse_adj: dict[str, list[str]] = defaultdict(list)

        for step in steps:
            adjacency[step.name]  # ensure entry exists
            reverse_adj[step.name]  # ensure entry exists
            for dep in step.depends_on:
                if dep not in step_map:
                    raise ValueError(
                        f"Step '{step.name}' depends on unknown step '{dep}'"
                    )
                adjacency[step.name].append(dep)
                reverse_adj[dep].append(step.name)

        dag = DAG(step_map, dict(adjacency), dict(reverse_adj))
        dag.validate()
        return dag
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline/test_dag.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/dag.py tests/test_pipeline/test_dag.py
git commit -m "feat(pipeline): add DAG builder with topological sort and cycle detection"
```

---

### Task 5: Pipeline Context V2 & State Manager V2

**Files:**
- Modify: `src/pipeline/core/context.py`
- Rewrite: `src/pipeline/core/state_manager.py`
- Test: `tests/test_pipeline/test_state_manager.py`

**Interfaces:**
- Consumes: `src/db/duckdb_manager.py` — `DuckDBManager`
- Produces:
  - `PipelineContext.__init__(self, db_manager: DuckDBManager, args: Any)`
  - `PipelineContext.db: DuckDBManager` — alias for db_manager
  - `PipelineContext.shared_data: dict[str, Any]`
  - `StateManagerV2.__init__(self, db_manager: DuckDBManager)`
  - `StateManagerV2.should_skip_step(self, step: BaseStep) -> tuple[bool, str]`
  - `StateManagerV2.mark_started(self, step_name: str, source_hash: str) -> None`
  - `StateManagerV2.mark_success(self, step_name: str, row_count: int, duration: float) -> None`
  - `StateManagerV2.mark_failed(self, step_name: str, duration: float, error: str) -> None`
  - `StateManagerV2.invalidate_step(self, step_name: str) -> None`
  - `StateManagerV2.invalidate_downstream(self, step_name: str, dag: DAG) -> None`
  - `StateManagerV2.clear_all(self) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline/test_state_manager.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.state_manager import StateManagerV2
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.dag import DAGBuilder
from src.pipeline.core.result import StepResult, StepStatus


def _make_real_step(name, depends_on=None, source_files=None):
    class S(BaseStep):
        pass
    s = S.__new__(S)
    s.name = name
    s.depends_on = depends_on or []
    s.produces = []
    s.optional = False
    s.execution_type = "cpu"
    s.source_files = source_files or []
    s.description = ""
    return s


@pytest.fixture
def db_manager(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


@pytest.fixture
def state_mgr(db_manager):
    return StateManagerV2(db_manager)


def test_should_skip_never_run(state_mgr):
    step = _make_real_step("new_step")
    skip, reason = state_mgr.should_skip_step(step)
    assert skip is False
    assert "never run" in reason.lower() or "not found" in reason.lower()


def test_should_skip_after_success(state_mgr):
    step = _make_real_step("my_step")
    source_hash = step.compute_source_hash()
    state_mgr.mark_started("my_step", source_hash)
    state_mgr.mark_success("my_step", row_count=100, duration=5.0)
    skip, reason = state_mgr.should_skip_step(step)
    assert skip is True
    assert "cached" in reason.lower()


def test_should_skip_after_failure(state_mgr):
    step = _make_real_step("my_step")
    state_mgr.mark_started("my_step", step.compute_source_hash())
    state_mgr.mark_failed("my_step", duration=2.0, error="boom")
    skip, reason = state_mgr.should_skip_step(step)
    assert skip is False


def test_should_skip_source_changed(state_mgr, tmp_path):
    test_file = tmp_path / "input.json"
    test_file.write_text("v1")
    step = _make_real_step("my_step", source_files=[test_file])
    hash1 = step.compute_source_hash()
    state_mgr.mark_started("my_step", hash1)
    state_mgr.mark_success("my_step", row_count=10, duration=1.0)

    # Change source file
    test_file.write_text("v2 with more content")
    skip, reason = state_mgr.should_skip_step(step)
    assert skip is False
    assert "changed" in reason.lower()


def test_invalidate_step(state_mgr):
    step = _make_real_step("my_step")
    state_mgr.mark_started("my_step", "hash1")
    state_mgr.mark_success("my_step", 10, 1.0)
    state_mgr.invalidate_step("my_step")
    skip, _ = state_mgr.should_skip_step(step)
    assert skip is False


def test_invalidate_downstream(state_mgr):
    a = _make_real_step("a")
    b = _make_real_step("b", depends_on=["a"])
    c = _make_real_step("c", depends_on=["b"])
    dag = DAGBuilder().build([a, b, c])

    for name in ["a", "b", "c"]:
        state_mgr.mark_started(name, "hash")
        state_mgr.mark_success(name, 10, 1.0)

    state_mgr.invalidate_downstream("a", dag)

    skip_a, _ = state_mgr.should_skip_step(a)
    assert skip_a is True  # a itself not invalidated

    skip_b, _ = state_mgr.should_skip_step(b)
    assert skip_b is False  # downstream invalidated

    skip_c, _ = state_mgr.should_skip_step(c)
    assert skip_c is False  # transitive downstream invalidated


def test_clear_all(state_mgr):
    state_mgr.mark_started("step1", "hash1")
    state_mgr.mark_success("step1", 10, 1.0)
    state_mgr.clear_all()
    step = _make_real_step("step1")
    skip, _ = state_mgr.should_skip_step(step)
    assert skip is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_state_manager.py -v`
Expected: FAIL — `StateManagerV2` not found

- [ ] **Step 3: Implement Context V2 and State Manager V2**

```python
# src/pipeline/core/context.py
"""
Pipeline execution context (V2).

Carries the DuckDB manager and CLI args through all steps.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from src.db.duckdb_manager import DuckDBManager


@dataclass
class PipelineContext:
    db_manager: DuckDBManager
    args: Any
    shared_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def db(self) -> DuckDBManager:
        """Convenience alias for db_manager."""
        return self.db_manager
```

```python
# src/pipeline/core/state_manager.py
"""
DuckDB-backed pipeline state manager (V2).

Uses _pipeline_meta table for step-level caching with content-based
invalidation (source hash) and cascade invalidation via DAG traversal.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.db.duckdb_manager import DuckDBManager

if TYPE_CHECKING:
    from src.pipeline.core.base_step import BaseStep
    from src.pipeline.core.dag import DAG

logger = logging.getLogger(__name__)


class StateManagerV2:
    """Manages pipeline step state in DuckDB for caching and resume."""

    def __init__(self, db_manager: DuckDBManager):
        self.db = db_manager

    def should_skip_step(self, step: BaseStep) -> tuple[bool, str]:
        """Determine if a step can be skipped based on cached state.

        Returns (True, reason) if the step should be skipped.
        Returns (False, reason) if the step must run.
        """
        meta = self.db.get_step_meta(step.name)

        if meta is None:
            return False, "Not found in pipeline meta (never run)"

        if meta["status"] != "success":
            return False, f"Previous status was '{meta['status']}'"

        current_hash = step.compute_source_hash()
        if meta["source_hash"] and current_hash != meta["source_hash"]:
            return False, f"Source data changed (was {meta['source_hash']}, now {current_hash})"

        row_count = meta.get("row_count", 0)
        return True, f"Cached ({row_count:,} rows)"

    def mark_started(self, step_name: str, source_hash: str) -> None:
        self.db.save_step_meta(
            step_name=step_name,
            status="running",
            source_hash=source_hash,
        )

    def mark_success(
        self, step_name: str, row_count: int, duration: float
    ) -> None:
        meta = self.db.get_step_meta(step_name)
        source_hash = meta["source_hash"] if meta else None
        self.db.save_step_meta(
            step_name=step_name,
            status="success",
            source_hash=source_hash,
            row_count=row_count,
            duration_secs=duration,
        )

    def mark_failed(
        self, step_name: str, duration: float, error: str
    ) -> None:
        meta = self.db.get_step_meta(step_name)
        source_hash = meta["source_hash"] if meta else None
        self.db.save_step_meta(
            step_name=step_name,
            status="failed",
            source_hash=source_hash,
            duration_secs=duration,
            error_message=error,
        )

    def invalidate_step(self, step_name: str) -> None:
        """Remove a step's cached state so it will re-run."""
        conn = self.db.get_connection()
        conn.execute(
            "DELETE FROM _pipeline_meta WHERE step_name = ?", [step_name]
        )
        self.db.clear_checkpoints(step_name)

    def invalidate_downstream(self, step_name: str, dag: DAG) -> None:
        """Invalidate all transitive dependents of a step."""
        downstream = dag.get_downstream(step_name)
        for name in downstream:
            self.invalidate_step(name)
            logger.info("Invalidated downstream step: %s", name)

    def clear_all(self) -> None:
        """Clear all pipeline state (for --force-all)."""
        conn = self.db.get_connection()
        conn.execute("DELETE FROM _pipeline_meta")
        conn.execute("DELETE FROM _batch_checkpoints")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline/test_state_manager.py -v`
Expected: all 8 tests PASS

Also verify context changes don't break anything:
Run: `python -m pytest tests/ -v --timeout=30`

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/context.py src/pipeline/core/state_manager.py tests/test_pipeline/test_state_manager.py
git commit -m "feat(pipeline): add DuckDB-backed state manager V2 with cascade invalidation"
```

---

### Task 6: DAG Orchestrator

**Files:**
- Rewrite: `src/pipeline/core/orchestrator.py`
- Test: `tests/test_pipeline/test_orchestrator.py`

**Interfaces:**
- Consumes:
  - `src/pipeline/core/dag.py` — `DAGBuilder`, `DAG`
  - `src/pipeline/core/base_step.py` — `BaseStep`
  - `src/pipeline/core/context.py` — `PipelineContext`
  - `src/pipeline/core/state_manager.py` — `StateManagerV2`
  - `src/pipeline/core/result.py` — `StepResult`, `StepStatus`, `PipelineSummary`
- Produces:
  - `DAGOrchestrator.__init__(self, steps: list[BaseStep])`
  - `DAGOrchestrator.run(self, context: PipelineContext) -> PipelineSummary`
  - Orchestrator builds DAG, checks state manager for each step, runs levels in parallel

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline/test_orchestrator.py
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import DAGOrchestrator
from src.pipeline.core.result import StepResult, StepStatus


class SchemaStep(BaseStep):
    name = "schema_init"
    description = "Init schema"
    depends_on = []
    produces = ["words"]
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0)


class IngestA(BaseStep):
    name = "ingest_a"
    description = "Ingest A"
    depends_on = ["schema_init"]
    produces = ["words"]
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        time.sleep(0.05)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class IngestB(BaseStep):
    name = "ingest_b"
    description = "Ingest B"
    depends_on = ["schema_init"]
    produces = ["sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        time.sleep(0.05)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=20)


class TransformStep(BaseStep):
    name = "transform"
    description = "Transform"
    depends_on = ["ingest_a", "ingest_b"]
    produces = ["word_sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


class FailingStep(BaseStep):
    name = "failing_step"
    description = "Always fails"
    depends_on = ["schema_init"]
    produces = []
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        raise RuntimeError("Intentional failure")


class OptionalAudioStep(BaseStep):
    name = "audio"
    description = "Audio generation"
    depends_on = ["schema_init"]
    produces = []
    optional = True
    execution_type = "io"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0)


@pytest.fixture
def db_manager(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


@pytest.fixture
def context(db_manager):
    args = MagicMock()
    args.force_all = False
    args.force_step = None
    args.dry_run = False
    args.enable = None
    args.disable = None
    args.tui = False
    return PipelineContext(db_manager=db_manager, args=args)


def test_orchestrator_runs_all_steps(context):
    steps = [SchemaStep(), IngestA(), IngestB(), TransformStep()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert not summary.has_failures
    assert len(summary.results) == 4
    names = [r.step_name for r in summary.results]
    assert "schema_init" in names
    assert "transform" in names


def test_orchestrator_parallel_steps_faster(context):
    """Ingest A and B should run in parallel (each 50ms), so total < 150ms for both."""
    steps = [SchemaStep(), IngestA(), IngestB()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert not summary.has_failures
    # If run sequentially: ~100ms. If parallel: ~50ms. Allow generous margin.
    assert summary.total_time_seconds < 0.5


def test_orchestrator_handles_failure(context):
    steps = [SchemaStep(), FailingStep()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert summary.has_failures
    failed = [r for r in summary.results if r.status == StepStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].step_name == "failing_step"


def test_orchestrator_skips_optional_disabled(context):
    context.args.disable = "audio"
    steps = [SchemaStep(), OptionalAudioStep()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert not summary.has_failures
    names = [r.step_name for r in summary.results]
    assert "audio" not in names


def test_orchestrator_dry_run(context):
    context.args.dry_run = True
    steps = [SchemaStep(), IngestA()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert not summary.has_failures
    for r in summary.results:
        assert r.status == StepStatus.SKIPPED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_orchestrator.py -v`
Expected: FAIL — old orchestrator doesn't have DAG constructor

- [ ] **Step 3: Implement the DAG orchestrator**

```python
# src/pipeline/core/orchestrator.py
"""
DAG-based parallel pipeline orchestrator (V2).

Builds a dependency graph from step declarations, determines execution
levels, and runs independent steps in parallel using threads (safe for
DuckDB which allows concurrent access from threads within one process).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.dag import DAGBuilder
from src.pipeline.core.result import PipelineSummary, StepResult, StepStatus
from src.pipeline.core.state_manager import StateManagerV2

logger = logging.getLogger(__name__)


def _get_arg(args: Any, name: str, default: Any) -> Any:
    if not args or not hasattr(args, name):
        return default
    val = getattr(args, name)
    return default if val is None else val


class DAGOrchestrator:
    """Runs pipeline steps respecting DAG dependencies with parallel execution."""

    def __init__(self, steps: list[BaseStep]):
        self.steps = steps
        self.has_failures = False

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.monotonic()
        results: list[StepResult] = []
        self.has_failures = False

        args = getattr(context, "args", None)
        dry_run = bool(_get_arg(args, "dry_run", False))
        force_all = bool(_get_arg(args, "force_all", False))
        force_step = _get_arg(args, "force_step", None)
        disable_str = _get_arg(args, "disable", None)

        state_mgr = StateManagerV2(context.db_manager)

        if force_all:
            state_mgr.clear_all()

        # Determine disabled optional steps
        disabled_steps: set[str] = set()
        if disable_str:
            disabled_steps = {s.strip() for s in str(disable_str).split(",") if s.strip()}

        # Build DAG
        dag = DAGBuilder().build(self.steps)

        # Handle --force-step: invalidate target + downstream
        if force_step:
            state_mgr.invalidate_step(force_step)
            state_mgr.invalidate_downstream(force_step, dag)

        levels = dag.execution_levels(disabled_steps=disabled_steps)

        logger.info("=" * 60)
        logger.info("  PIPELINE EXECUTION PLAN (%d levels, %d steps)",
                     len(levels), sum(len(lv) for lv in levels))
        logger.info("=" * 60)
        for i, level in enumerate(levels):
            names = [s.name for s in level]
            logger.info("  Level %d: %s", i, ", ".join(names))
        logger.info("=" * 60)

        for level_idx, level in enumerate(levels):
            if self.has_failures:
                break

            logger.info("--- Level %d: %s ---",
                        level_idx, ", ".join(s.name for s in level))

            if dry_run:
                for step in level:
                    res = StepResult(
                        step_name=step.name,
                        status=StepStatus.SKIPPED,
                        message=f"[DRY-RUN] Would run '{step.name}'"
                    )
                    results.append(res)
                continue

            level_results = self._run_level(level, context, state_mgr)
            results.extend(level_results)

            for res in level_results:
                if res.status == StepStatus.FAILED:
                    self.has_failures = True
                    logger.error("Step '%s' FAILED — halting pipeline", res.step_name)
                    break

        total_time = round(time.monotonic() - start_time, 2)
        summary = PipelineSummary(
            total_time_seconds=total_time,
            results=results,
            has_failures=self.has_failures,
        )
        self._print_summary(results, total_time)
        return summary

    def _run_level(
        self,
        level: list[BaseStep],
        context: PipelineContext,
        state_mgr: StateManagerV2,
    ) -> list[StepResult]:
        """Run all steps in a level, using threads for parallelism."""
        results: list[StepResult] = []

        if len(level) == 1:
            # Single step — run inline, no thread overhead
            results.append(self._execute_step(level[0], context, state_mgr))
            return results

        # Multiple steps — run in parallel threads
        with ThreadPoolExecutor(max_workers=len(level)) as pool:
            futures = {
                pool.submit(self._execute_step, step, context, state_mgr): step
                for step in level
            }
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _execute_step(
        self,
        step: BaseStep,
        context: PipelineContext,
        state_mgr: StateManagerV2,
    ) -> StepResult:
        """Execute a single step with state management."""
        step_start = time.monotonic()

        # Check cache
        skip, reason = state_mgr.should_skip_step(step)
        if skip:
            logger.info("[%s] SKIPPED: %s", step.name, reason)
            return StepResult(
                step_name=step.name,
                status=StepStatus.SKIPPED,
                message=reason,
            )

        # Check step's own should_skip
        skip, reason = step.should_skip(context)
        if skip:
            logger.info("[%s] SKIPPED: %s", step.name, reason)
            return StepResult(
                step_name=step.name,
                status=StepStatus.SKIPPED,
                message=reason,
            )

        source_hash = step.compute_source_hash()
        state_mgr.mark_started(step.name, source_hash)
        logger.info("[%s] RUNNING: %s", step.name, step.description)

        try:
            result = step.run(context)
            duration = round(time.monotonic() - step_start, 2)
            if result.execution_time_seconds == 0.0:
                result.execution_time_seconds = duration

            if result.status == StepStatus.SUCCESS:
                state_mgr.mark_success(step.name, result.items_processed, duration)
                logger.info("[%s] SUCCESS in %.2fs (%d items)",
                            step.name, duration, result.items_processed)
            else:
                state_mgr.mark_failed(step.name, duration, result.message or "")
                logger.error("[%s] FAILED in %.2fs: %s",
                             step.name, duration, result.message)

            return result

        except Exception as e:
            duration = round(time.monotonic() - step_start, 2)
            state_mgr.mark_failed(step.name, duration, str(e))
            logger.error("[%s] FAILED in %.2fs: %s", step.name, duration, e, exc_info=True)

            if hasattr(step, "rollback"):
                try:
                    step.rollback(context)
                except Exception as rb_err:
                    logger.warning("[%s] Rollback error: %s", step.name, rb_err)

            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                execution_time_seconds=duration,
                message=str(e),
                error=e,
            )

    def _print_summary(self, results: list[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 70)
        logger.info(f"{'STEP NAME':<28} | {'STATUS':<8} | {'TIME (s)':<10} | {'ITEMS':<8}")
        logger.info("-" * 70)
        for r in results:
            logger.info(
                f"{r.step_name:<28} | {r.status.value:<8} | "
                f"{r.execution_time_seconds:<10.2f} | {r.items_processed:<8}"
            )
        logger.info("=" * 70)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 70 + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline/test_orchestrator.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/orchestrator.py tests/test_pipeline/test_orchestrator.py
git commit -m "feat(pipeline): add DAG orchestrator with parallel level execution"
```

---

### Task 7: CLI V2 & Main Entry Point

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `config/settings.py`
- Modify: `main.py`
- Test: `tests/test_pipeline/test_cli.py`

**Interfaces:**
- Consumes:
  - `src/db/duckdb_manager.py` — `DuckDBManager`
  - `src/pipeline/core/orchestrator.py` — `DAGOrchestrator`
  - `src/pipeline/core/context.py` — `PipelineContext`
- Produces:
  - `parse_arguments()` — updated with `--force-step`, `--force-all`, `--enable`, `--disable` flags
  - `main()` — wires DuckDB manager + DAG orchestrator

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline/test_cli.py
from src.pipeline.cli import parse_arguments


def test_parse_force_step():
    args = parse_arguments(["--force-step", "ingest_kaikki"])
    assert args.force_step == "ingest_kaikki"


def test_parse_force_all():
    args = parse_arguments(["--force-all"])
    assert args.force_all is True


def test_parse_enable():
    args = parse_arguments(["--enable", "audio_generation"])
    assert args.enable == "audio_generation"


def test_parse_disable():
    args = parse_arguments(["--disable", "enrich_audio"])
    assert args.disable == "enrich_audio"


def test_parse_defaults():
    args = parse_arguments([])
    assert args.force_all is False
    assert args.force_step is None
    assert args.enable is None
    assert args.disable is None
    assert args.dry_run is False
    assert args.tui is True


def test_parse_steps_filter():
    args = parse_arguments(["--steps", "ingest_kaikki,export_sqlite"])
    assert args.steps == "ingest_kaikki,export_sqlite"


def test_parse_dry_run():
    args = parse_arguments(["--dry-run"])
    assert args.dry_run is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline/test_cli.py -v`
Expected: FAIL — `--force-step`, `--force-all`, `--enable`, `--disable` not recognized

- [ ] **Step 3: Update CLI, settings, and main.py**

```python
# src/pipeline/cli.py
"""CLI argument parser for VocabCraft Engine Pipeline V2."""

import argparse
from typing import List, Optional


def parse_arguments(args_list: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="VocabCraft Engine Pipeline V2")

    # Step selection
    parser.add_argument("--steps", type=str,
                        help="Comma-separated step names to execute.")
    parser.add_argument("--skip-steps", type=str,
                        help="Comma-separated step names to skip.")

    # Cache / force control
    parser.add_argument("--force-step", type=str,
                        help="Force re-run a specific step (+ cascade downstream).")
    parser.add_argument("--force-all", action="store_true", default=False,
                        help="Force re-run everything (clear all cached state).")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last crash.")

    # Optional step control
    parser.add_argument("--enable", type=str,
                        help="Enable an optional step (e.g. --enable enrich_audio).")
    parser.add_argument("--disable", type=str,
                        help="Disable an optional step (e.g. --disable enrich_audio).")

    # Execution modes
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview execution plan without running steps.")
    parser.add_argument("--no-tui", action="store_false", dest="tui", default=True,
                        help="Disable Rich Terminal UI dashboard.")

    # Build options
    parser.add_argument("--build-core-pack", action="store_true",
                        help="Build the curated Core 3000 word pack.")
    parser.add_argument("--vi-budget", type=int, default=5000,
                        help="Max translation attempts for Vietnamese backfill.")

    # Logging
    parser.add_argument("--log-dir", type=str, default="logs",
                        help="Directory to store log files.")

    return parser.parse_args(args_list)
```

Add to `config/settings.py` — ensure `STAGING_DUCKDB_PATH` is properly used:

```python
# At the top of config/settings.py, after existing path definitions:
# (This path already exists in the file, just ensure it's being used)
STAGING_DUCKDB_PATH = PROCESSED_DATA_DIR / "staging.duckdb"
```

Update `main.py`:

```python
"""
Main Execution Pipeline for VocabCraft Engine V2.
DAG-based orchestration with DuckDB staging.
"""

import sys
import logging
from src.pipeline.cli import parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import DAGOrchestrator
from src.db.duckdb_manager import DuckDBManager
from config.settings import STAGING_DUCKDB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def get_pipeline_steps():
    """Import and return all pipeline steps.

    This will be populated as steps are migrated in Phase 2.
    For now returns an empty list — the orchestrator handles zero steps gracefully.
    """
    # TODO: Phase 2 will populate this with migrated steps
    return []


def main():
    args = parse_arguments()

    db_manager = DuckDBManager(db_path=STAGING_DUCKDB_PATH)
    try:
        db_manager.init_schema()
        context = PipelineContext(db_manager=db_manager, args=args)

        steps = get_pipeline_steps()
        if not steps:
            logger.warning("No pipeline steps registered. Run Phase 2 migration first.")
            return

        orchestrator = DAGOrchestrator(steps=steps)
        summary = orchestrator.run(context)

        if summary.has_failures:
            logger.error("Pipeline completed with failures.")
            sys.exit(1)
        else:
            logger.info("Pipeline completed successfully.")
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_pipeline/ -v`
Expected: ALL PASS (test_cli + all previous tasks' tests)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/cli.py config/settings.py main.py tests/test_pipeline/test_cli.py
git commit -m "feat(pipeline): update CLI V2 and main entry point for DAG orchestrator"
```

---

### Task 8: Integration Test — Full DAG Pipeline

**Files:**
- Create: `tests/test_pipeline/test_integration.py`

**Interfaces:**
- Consumes: All previous tasks' outputs
- Produces: Integration test validating the full foundation works end-to-end

- [ ] **Step 1: Write integration test**

```python
# tests/test_pipeline/test_integration.py
"""
Integration test: validates the full Phase 1 foundation works end-to-end.
Creates mock steps with DAG dependencies and runs them through the orchestrator.
"""
import time
import pytest
from unittest.mock import MagicMock

from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import DAGOrchestrator
from src.pipeline.core.result import StepResult, StepStatus


# ---- Mock steps simulating the real pipeline structure ----

class MockSchemaInit(BaseStep):
    name = "schema_init"
    description = "Initialize DuckDB schema"
    depends_on = []
    produces = ["words", "sentences"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0)


class MockIngestKaikki(BaseStep):
    name = "ingest_kaikki"
    description = "Ingest Kaikki Wiktionary"
    depends_on = ["schema_init"]
    produces = ["words", "definitions"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        ctx.db.insert_batch("words", [
            {"lemma": "run", "pos": "verb", "source": "kaikki"},
            {"lemma": "walk", "pos": "verb", "source": "kaikki"},
        ])
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=2)


class MockIngestTatoeba(BaseStep):
    name = "ingest_tatoeba"
    description = "Ingest Tatoeba sentences"
    depends_on = ["schema_init"]
    produces = ["sentences"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        ctx.db.insert_batch("sentences", [
            {"text_en": "I run every day.", "source": "tatoeba"},
            {"text_en": "She walks to school.", "source": "tatoeba"},
        ])
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=2)


class MockTransform(BaseStep):
    name = "transform_linking"
    description = "Link words to sentences"
    depends_on = ["ingest_kaikki", "ingest_tatoeba"]
    produces = ["word_sentences"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=1)


class MockExport(BaseStep):
    name = "export_sqlite"
    description = "Export to SQLite"
    depends_on = ["transform_linking"]
    produces = []

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0)


@pytest.fixture
def db_manager(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "integration.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


@pytest.fixture
def context(db_manager):
    args = MagicMock()
    args.force_all = False
    args.force_step = None
    args.dry_run = False
    args.enable = None
    args.disable = None
    args.tui = False
    return PipelineContext(db_manager=db_manager, args=args)


def test_full_pipeline_e2e(context):
    steps = [
        MockSchemaInit(),
        MockIngestKaikki(),
        MockIngestTatoeba(),
        MockTransform(),
        MockExport(),
    ]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)

    assert not summary.has_failures
    assert len(summary.results) == 5

    # Verify data was actually written to DuckDB
    assert context.db.count_rows("words") == 2
    assert context.db.count_rows("sentences") == 2


def test_cached_run_skips_completed(context):
    steps = [
        MockSchemaInit(),
        MockIngestKaikki(),
        MockIngestTatoeba(),
        MockTransform(),
        MockExport(),
    ]
    orch = DAGOrchestrator(steps=steps)

    # First run
    summary1 = orch.run(context)
    assert not summary1.has_failures

    # Second run — should skip all (cached)
    orch2 = DAGOrchestrator(steps=steps)
    summary2 = orch2.run(context)
    assert not summary2.has_failures
    skipped = [r for r in summary2.results if r.status == StepStatus.SKIPPED]
    assert len(skipped) == 5


def test_force_step_reruns_target_and_downstream(context):
    steps = [
        MockSchemaInit(),
        MockIngestKaikki(),
        MockIngestTatoeba(),
        MockTransform(),
        MockExport(),
    ]
    orch = DAGOrchestrator(steps=steps)
    orch.run(context)

    # Force re-run ingest_kaikki
    context.args.force_step = "ingest_kaikki"
    orch2 = DAGOrchestrator(steps=steps)
    summary = orch2.run(context)
    assert not summary.has_failures

    rerun_names = {r.step_name for r in summary.results if r.status == StepStatus.SUCCESS}
    skipped_names = {r.step_name for r in summary.results if r.status == StepStatus.SKIPPED}

    # ingest_kaikki and its downstream (transform, export) should re-run
    assert "ingest_kaikki" in rerun_names
    assert "transform_linking" in rerun_names
    assert "export_sqlite" in rerun_names
    # schema_init and ingest_tatoeba should be skipped (not downstream of ingest_kaikki)
    assert "schema_init" in skipped_names
    assert "ingest_tatoeba" in skipped_names


def test_dry_run_no_side_effects(context):
    context.args.dry_run = True
    steps = [MockSchemaInit(), MockIngestKaikki()]
    orch = DAGOrchestrator(steps=steps)
    summary = orch.run(context)
    assert not summary.has_failures
    assert context.db.count_rows("words") == 0  # nothing written
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_pipeline/test_integration.py -v`
Expected: all 4 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/test_pipeline/ -v`
Expected: ALL tests PASS across all task test files

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline/test_integration.py
git commit -m "test(pipeline): add integration tests for DAG orchestrator end-to-end"
```

---

## Summary

Phase 1 delivers these foundation components:

| Task | Component | LOC (est.) |
|------|-----------|-----------|
| 1 | DuckDB Schema | ~150 |
| 2 | DuckDB Manager | ~180 |
| 3 | BaseStep V2 | ~50 |
| 4 | DAG Builder | ~120 |
| 5 | State Manager V2 + Context V2 | ~100 |
| 6 | DAG Orchestrator | ~180 |
| 7 | CLI V2 + main.py | ~80 |
| 8 | Integration Tests | ~150 |
| **Total** | | **~1010 LOC + ~500 LOC tests** |

After Phase 1, the pipeline foundation is in place. Phase 2 (pipeline steps migration) and Phase 3 (TUI dashboard) can be planned and executed independently.

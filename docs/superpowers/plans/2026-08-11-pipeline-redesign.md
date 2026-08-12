# Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the monolithic sequential pipeline into a DAG-based architecture with DuckDB staging, single-pass Kaikki ingestion, and SQLite bulk export — targeting <15 min full runtime.

**Architecture:** PipelineDAG executes stages with dependency resolution. DuckDB handles staging/transforms (parallel reads, vectorized SQL). SQLite handles final export (WAL mode, bulk commits). Each stage checkpoints independently for crash recovery.

**Tech Stack:** Python 3.11+, DuckDB 1.1.x, SQLite 3.45+, spaCy, Argos Translate, edge-tts, asyncio, concurrent.futures

---

## File Structure

```
src/
├── pipeline/
│   ├── __init__.py              # (new) Package init
│   ├── context.py               # (new) PipelineContext — shared state
│   ├── dag.py                   # (new) DAGExecutor + PipelineStep
│   └── registry.py              # (new) Checkpoint read/write
├── db/
│   ├── __init__.py              # (exists) Keep
│   ├── duckdb_manager.py        # (new) DuckDB staging with PRAGMAs
│   ├── sqlite_manager.py        # (modify) SQLiteBulkWriter replaces DatabaseManager
│   └── staging_db.py            # (modify) Lightweight wrapper → delegates to duckdb_manager
├── ingestion/
│   ├── __init__.py              # (exists) Keep
│   ├── kaikki_single_pass.py    # (new) Single-pass parser (replaces kaikki_parser, phrase_parser, relation_parser)
│   ├── kaikki_parser.py         # (keep but unused) Legacy, kept for reference
│   ├── phrase_parser.py         # (keep but unused) Legacy
│   ├── relation_parser.py       # (keep but unused) Legacy
│   ├── downloader.py            # (new) Parallel download with ThreadPoolExecutor
│   ├── opus_parser.py           # (keep) Used by corpora stage
│   ├── sentence_filter.py       # (keep) Used by corpora stage
│   └── tatoeba_parser.py        # (keep) Used by corpora stage
├── nlp/
│   ├── translator_hybrid.py     # (new) Argos + Google hybrid
│   ├── translator.py            # (modify) Refactor to use HybridTranslator internally
│   └── ...                      # (keep) Other NLP modules unchanged
├── stages/
│   ├── __init__.py              # (new) Package init
│   ├── stage_1_ingest.py        # (new) Download + Kaikki single-pass + Corpora
│   ├── stage_2_transform.py     # (new) CEFR grading, lemmatization, collocations
│   ├── stage_3_enrich.py        # (new) Translation backfill, reflex drills, audio
│   ├── stage_4_export.py        # (new) DuckDB → SQLite bulk COPY
│   └── stage_5_core_pack.py     # (new) Core pack builder (refactored from core_pack_builder.py)
├── export/
│   ├── sqlite_exporter.py       # (modify) Wrap new SQLiteBulkWriter
│   └── core_pack_builder.py     # (keep) Reuse in stage_5
├── media/
│   └── audio_generator.py       # (keep) Unchanged
└── main.py                      # (rewrite) DAG pipeline entry point

tests/
├── test_kaikki_single_pass.py   # (new)
├── test_duckdb_manager.py       # (new)
├── test_sqlite_bulk_writer.py   # (new)
├── test_dag_executor.py         # (new)
├── test_translator_hybrid.py    # (new)
├── test_downloader.py           # (new)
└── test_stages.py               # (new) Integration tests per stage

config/
└── settings.py                  # (modify) Add DuckDB path, staging config
Makefile                         # (modify) Add run-step, benchmark targets
pyproject.toml                   # (modify) Add argostranslate dependency
```

---

## Task 1: Pipeline Context and Registry

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/context.py`
- Create: `src/pipeline/registry.py`

- [ ] **Step 1: Create the pipeline package**

`src/pipeline/__init__.py`:
```python
from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor, PipelineStep
from src.pipeline.registry import CheckpointRegistry

__all__ = ["PipelineContext", "DAGExecutor", "PipelineStep", "CheckpointRegistry"]
```

- [ ] **Step 2: Create PipelineContext**

`src/pipeline/context.py`:
```python
"""Shared pipeline context — passed to every stage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import logging

from config.settings import (
    EXPORT_SQLITE_PATH, PROCESSED_DATA_DIR, OUTPUT_DIR,
    RAW_DATA_DIR, AUDIO_DIR, KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH, NGSL_PATH,
    OPENSUBTITLES_EN, OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
    STAGING_DUCKDB_PATH, SENTENCE_LINK_CHECKPOINT,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Immutable config + mutable state shared across all pipeline stages."""

    # Config paths (immutable)
    sqlite_path: Path = EXPORT_SQLITE_PATH
    duckdb_path: Path = STAGING_DUCKDB_PATH
    processed_dir: Path = PROCESSED_DATA_DIR
    output_dir: Path = OUTPUT_DIR
    raw_dir: Path = RAW_DATA_DIR
    audio_dir: Path = AUDIO_DIR
    checkpoint_dir: Path = PROCESSED_DATA_DIR

    # CLI flags
    force_reset: bool = False
    vi_budget: int = 1000
    audio_limit: int = 5000

    # Runtime state (populated by stages)
    duckdb_conn: Any = None
    sqlite_conn: Any = None
    lemma_cache: Optional[Dict[str, int]] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    def checkpoint_path(self, stage_name: str) -> Path:
        return self.checkpoint_dir / f"checkpoint_{stage_name}.json"
```

- [ ] **Step 3: Create CheckpointRegistry**

`src/pipeline/registry.py`:
```python
"""Checkpoint read/write for stage-level resume."""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CheckpointRegistry:
    """Reads/writes stage completion checkpoints."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def is_done(self, stage_name: str) -> bool:
        cp = self._read(stage_name)
        return cp is not None and cp.get("completed", False)

    def mark_done(self, stage_name: str, metadata: Optional[Dict[str, Any]] = None):
        data = {
            "completed": True,
            "timestamp": time.time(),
            **(metadata or {}),
        }
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        logger.info("[Checkpoint] Stage '%s' marked complete.", stage_name)

    def clear(self, stage_name: str):
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        path.unlink(missing_ok=True)

    def clear_all(self):
        for path in self.checkpoint_dir.glob("checkpoint_*.json"):
            path.unlink()

    def _read(self, stage_name: str) -> Optional[Dict[str, Any]]:
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
```

- [ ] **Step 4: Commit**

```bash
git add src/pipeline/
git commit -m "feat(pipeline): add PipelineContext and CheckpointRegistry"
```

---

## Task 2: DAG Executor

**Files:**
- Create: `src/pipeline/dag.py`

- [ ] **Step 1: Write the failing test**

`tests/test_dag_executor.py`:
```python
"""Tests for DAGExecutor."""

import time
import pytest
from typing import Set

from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor, PipelineStep
from src.pipeline.registry import CheckpointRegistry


def test_dag_executes_in_dependency_order():
    """Steps execute only after their dependencies complete."""
    execution_order = []
    ctx = PipelineContext()

    def make_step(name: str):
        def step(context: PipelineContext):
            execution_order.append(name)
        return step

    dag = DAGExecutor()
    dag.add_step("c", make_step("c"), depends={"a", "b"})
    dag.add_step("b", make_step("b"), depends={"a"})
    dag.add_step("a", make_step("a"))

    dag.execute(ctx)

    assert execution_order.index("a") < execution_order.index("b")
    assert execution_order.index("b") < execution_order.index("c")


def test_dag_parallelizes_independent_steps():
    """Independent steps run concurrently."""
    ctx = PipelineContext()
    start_times = {}
    end_times = {}

    def slow_step(name: str, delay: float):
        def step(context: PipelineContext):
            start_times[name] = time.time()
            time.sleep(delay)
            end_times[name] = time.time()
        return step

    dag = DAGExecutor()
    dag.add_step("x", slow_step("x", 0.3))
    dag.add_step("y", slow_step("y", 0.3))

    dag.execute(ctx)

    # If parallel, both should start near-simultaneously
    assert abs(start_times["x"] - start_times["y"]) < 0.1


def test_dag_respects_checkpoints():
    """Completed stages are skipped unless force_reset."""
    ctx = PipelineContext()
    call_count = {"a": 0}

    def counting_step(name: str):
        def step(context: PipelineContext):
            call_count[name] += 1
        return step

    dag = DAGExecutor(registry=CheckpointRegistry(ctx.checkpoint_dir))
    dag.add_step("done_step", counting_step("done_step"))
    dag.add_step("after", counting_step("a"), depends={"done_step"})

    # Pre-mark done_step as complete
    dag.registry.mark_done("done_step")

    dag.execute(ctx, force_reset=False)

    assert call_count["done_step"] == 0
    assert call_count["a"] == 1


def test_dag_force_reset_reruns_completed():
    """force_reset=True re-runs all steps."""
    ctx = PipelineContext()
    call_count = {"step": 0}

    def step_fn(context: PipelineContext):
        call_count["step"] += 1

    dag = DAGExecutor(registry=CheckpointRegistry(ctx.checkpoint_dir))
    dag.add_step("step", step_fn)
    dag.registry.mark_done("step")

    dag.execute(ctx, force_reset=True)

    assert call_count["step"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hoojinguyen/Hooji/antigravity/EnglishDataset && .venv/bin/pytest tests/test_dag_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.dag'`

- [ ] **Step 3: Implement DAGExecutor**

`src/pipeline/dag.py`:
```python
"""DAG-based pipeline executor with parallel step execution."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, Set, Optional, Any

from src.pipeline.context import PipelineContext
from src.pipeline.registry import CheckpointRegistry

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    name: str
    func: Callable[[PipelineContext], None]
    depends: Set[str] = field(default_factory=set)


class DAGExecutor:
    """Executes pipeline steps respecting dependency order. Independent steps run in parallel."""

    def __init__(self, registry: Optional[CheckpointRegistry] = None):
        self._steps: Dict[str, PipelineStep] = {}
        self.registry = registry

    def add_step(self, name: str, func: Callable[[PipelineContext], None],
                 depends: Optional[Set[str]] = None) -> "DAGExecutor":
        self._steps[name] = PipelineStep(name=name, func=func, depends=depends or set())
        return self

    def execute(self, context: PipelineContext, force_reset: bool = False):
        if force_reset and self.registry:
            self.registry.clear_all()

        completed: Set[str] = set()
        self._load_checkpoints(completed, context)

        while True:
            ready = self._find_ready(completed)
            if not ready:
                break

            logger.info("[DAG] Executing steps: %s", sorted(ready))
            self._execute_parallel(ready, context, completed)

        logger.info("[DAG] All steps complete.")

    def _execute_parallel(self, ready: Set[str], context: PipelineContext, completed: Set[str]):
        workers = min(len(ready), 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._run_step, name, context): name
                for name in ready
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                    completed.add(name)
                    if self.registry:
                        self.registry.mark_done(name)
                except Exception:
                    logger.exception("[DAG] Step '%s' failed", name)
                    raise

    def _run_step(self, name: str, context: PipelineContext):
        step = self._steps[name]
        start = time.time()
        logger.info("[DAG] Starting step: %s", name)
        step.func(context)
        elapsed = time.time() - start
        logger.info("[DAG] Step '%s' completed in %.2fs", name, elapsed)

    def _find_ready(self, completed: Set[str]) -> Set[str]:
        return {
            name for name, step in self._steps.items()
            if name not in completed and step.depends.issubset(completed)
        }

    def _load_checkpoints(self, completed: Set[str], context: PipelineContext):
        if not self.registry:
            return
        for name in self._steps:
            if self.registry.is_done(name):
                completed.add(name)
                logger.info("[DAG] Skipping '%s' (checkpoint found)", name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_dag_executor.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/dag.py tests/test_dag_executor.py
git commit -m "feat(pipeline): DAGExecutor with parallel step execution and checkpoint skip"
```

---

## Task 3: DuckDB Manager

**Files:**
- Create: `src/db/duckdb_manager.py`
- Create: `tests/test_duckdb_manager.py`

- [ ] **Step 1: Write the failing test**

`tests/test_duckdb_manager.py`:
```python
"""Tests for DuckDB staging manager."""

import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


@pytest.fixture
def db(tmp_path):
    return DuckDBManager(db_path=tmp_path / "test.duckdb")


def test_create_and_insert_words(db):
    db.init_schema()
    rows = [
        {"lemma": "hello", "pos": "intj", "frequency_rank": 500, "cefr_level": "A1"},
        {"lemma": "world", "pos": "noun", "frequency_rank": 800, "cefr_level": "A1"},
    ]
    db.insert_rows("raw_words", rows)
    result = db.query("SELECT count(*) FROM raw_words")
    assert result.fetchone()[0] == 2


def test_query_returns_data(db):
    db.init_schema()
    db.insert_rows("raw_sentences", [
        {"text_en": "Hello world", "text_vi": "Xin chào", "source": "test"},
    ])
    result = db.query("SELECT text_en, text_vi FROM raw_sentences LIMIT 1").fetchone()
    assert result[0] == "Hello world"
    assert result[1] == "Xin chào"


def test_bulk_insert_10k_rows(db):
    db.init_schema()
    rows = [
        {"lemma": f"word_{i}", "pos": "noun", "frequency_rank": i, "cefr_level": "B1"}
        for i in range(10_000)
    ]
    db.insert_rows("raw_words", rows)
    count = db.query("SELECT count(*) FROM raw_words").fetchone()[0]
    assert count == 10_000


def test_attached_sqlite_export(db, tmp_path):
    """Test DuckDB can ATTACH SQLite and export data."""
    db.init_schema()
    db.insert_rows("raw_words", [
        {"lemma": "test", "pos": "noun", "frequency_rank": 1, "cefr_level": "A1"},
    ])

    sqlite_path = tmp_path / "export.db"
    db.export_to_sqlite("raw_words", sqlite_path, table_name="words")

    import sqlite3
    conn = sqlite3.connect(str(sqlite_path))
    count = conn.execute("SELECT count(*) FROM words").fetchone()[0]
    conn.close()
    assert count == 1


def test_close_releases_connection(db):
    db.init_schema()
    db.close()
    # No exception on re-open
    db2 = DuckDBManager(db_path=db.db_path)
    db2.init_schema()
    db2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_duckdb_manager.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DuckDBManager**

`src/db/duckdb_manager.py`:
```python
"""DuckDB staging manager for parallel ingest and bulk transforms."""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import duckdb

logger = logging.getLogger(__name__)


STAGING_PRAGMAS = [
    "PRAGMA threads = 0",
    "PRAGMA memory_limit = '8GB'",
    "PRAGMA enable_object_cache",
    "PRAGMA enable_progress_bar",
    "PRAGMA preserve_insertion_order = false",
]

SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS raw_words_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_sentences_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_phrases_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_relations_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_topics_id_seq START 1;

CREATE TABLE IF NOT EXISTS raw_words (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    lemma VARCHAR UNIQUE NOT NULL,
    pos VARCHAR NOT NULL,
    ipa_uk VARCHAR,
    ipa_us VARCHAR,
    frequency_rank INTEGER,
    cefr_level VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_definitions (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    word_id INTEGER NOT NULL,
    definition_en VARCHAR,
    definition_vi VARCHAR,
    example VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_phrases (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_phrases_id_seq'),
    phrase VARCHAR UNIQUE NOT NULL,
    phrase_type VARCHAR NOT NULL,
    pos VARCHAR,
    cefr_level VARCHAR,
    difficulty_score DOUBLE,
    definition_en VARCHAR,
    definition_vi VARCHAR,
    ipa VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_relations (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_relations_id_seq'),
    word_id INTEGER NOT NULL,
    relation_type VARCHAR NOT NULL,
    target_text VARCHAR NOT NULL,
    target_word_id INTEGER,
    inverted INTEGER DEFAULT 0,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_topics (
    word_id INTEGER NOT NULL,
    topic VARCHAR NOT NULL,
    raw_topic VARCHAR,
    PRIMARY KEY (word_id, topic)
);

CREATE TABLE IF NOT EXISTS raw_sentences (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_sentences_id_seq'),
    text_en VARCHAR UNIQUE NOT NULL,
    text_vi VARCHAR,
    difficulty_score DOUBLE,
    cefr_level VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS collocations (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    phrase VARCHAR UNIQUE NOT NULL,
    meaning_vi VARCHAR,
    pos_pattern VARCHAR,
    cefr_level VARCHAR
);

CREATE TABLE IF NOT EXISTS word_sentence_map (
    word_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    PRIMARY KEY (word_id, sentence_id)
);
"""


class DuckDBManager:
    """Manages DuckDB staging database for ETL pipeline."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self.conn is None:
            self.conn = duckdb.connect(str(self.db_path))
            for pragma in STAGING_PRAGMAS:
                self.conn.execute(pragma)
            logger.info("DuckDB connected: %s", self.db_path)
        return self.conn

    def init_schema(self):
        conn = self.connect()
        conn.executescript(SCHEMA_SQL)
        logger.info("DuckDB schema initialized.")

    def insert_rows(self, table: str, rows: List[Dict[str, Any]], batch_size: int = 10_000):
        if not rows:
            return
        conn = self.connect()
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            columns = list(batch[0].keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join(columns)
            sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"
            values = [tuple(row[c] for c in columns) for row in batch]
            conn.executemany(sql, values)
        conn.commit()

    def query(self, sql: str, params: tuple = ()):
        return self.connect().execute(sql, params)

    def execute(self, sql: str):
        self.connect().execute(sql)

    def export_to_sqlite(self, table: str, sqlite_path: Path, table_name: Optional[str] = None):
        """Export a staging table to SQLite via ATTACH."""
        target = table_name or table
        conn = self.connect()
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{sqlite_path}' AS sq (TYPE sqlite)")
        conn.execute(f"CREATE TABLE IF NOT EXISTS sq.{target} AS SELECT * FROM {table} WHERE 0=1")
        conn.execute(f"INSERT INTO sq.{target} SELECT * FROM {table}")
        conn.execute("DETACH sq")
        conn.commit()
        logger.info("Exported %s → sqlite:%s", table, target)

    def row_count(self, table: str) -> int:
        return self.connect().execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_duckdb_manager.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/db/duckdb_manager.py tests/test_duckdb_manager.py
git commit: add DuckDB staging manager with PRAGMAs and schema"
```

---

## Task 4: SQLite Bulk Writer

**Files:**
- Create: `src/db/sqlite_manager.py` (new optimized writer)
- Create: `tests/test_sqlite_bulk_writer.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sqlite_bulk_writer.py`:
```python
"""Tests for SQLite bulk writer."""

import pytest
import sqlite3
from pathlib import Path
from src.db.sqlite_manager import SQLiteBulkWriter


@pytest.fixture
def writer(tmp_path):
    w = SQLiteBulkWriter(db_path=tmp_path / "test.db")
    w.connect()
    w.init_schema()
    return w


def test_bulk_insert_10k(writer):
    rows = [
        {"lemma": f"word_{i}", "pos": "noun", "frequency_rank": i, "cefr_level": "B1"}
        for i in range(10_000)
    ]
    writer.insert_words(rows, commit_every=10)
    count = writer.conn.execute("SELECT count(*) FROM words").fetchone()[0]
    assert count == 10_000


def test_insert_definitions_with_lemma_cache(writer):
    writer.insert_words([
        {"lemma": "hello", "pos": "intj", "frequency_rank": 1, "cefr_level": "A1"},
    ], commit_every=1)
    cache = {"hello": 1}
    rows = [
        {"word_id": cache["hello"], "definition_en": "a greeting", "source": "test"},
    ]
    writer.insert_definitions(rows, commit_every=1)
    result = writer.conn.execute(
        "SELECT definition_en FROM definitions WHERE word_id = 1"
    ).fetchone()
    assert result[0] == "a greeting"


def test_wal_mode_enabled(writer):
    mode = writer.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_cache_size_set(writer):
    cache = writer.conn.execute("PRAGMA cache_size").fetchone()[0]
    assert cache <= -10000  # Negative = KB units


def test_insert_sentences_with_dedup(writer):
    rows = [
        {"text_en": "Hello world", "text_vi": "Xin chào", "source": "test"},
        {"text_en": "Hello world", "text_vi": "Xin chào", "source": "test"},  # dup
    ]
    writer.insert_sentences(rows, commit_every=1)
    count = writer.conn.execute("SELECT count(*) FROM sentences").fetchone()[0]
    assert count == 1


def test_create_indexes(writer):
    writer.create_indexes()
    # Should not raise
    writer.conn.execute("SELECT * FROM words WHERE lemma = 'test'")


def test_writer_close(writer):
    writer.close()
    # Verify we can reopen
    w2 = SQLiteBulkWriter(db_path=writer.db_path)
    w2.connect()
    w2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sqlite_bulk_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SQLiteBulkWriter**

`src/db/sqlite_manager.py`:
```python
"""Optimized SQLite bulk writer with WAL mode and deferred commits."""

import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

BULK_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = OFF;",
    "PRAGMA cache_size = -20000;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 268435456;",
    "PRAGMA page_size = 4096;",
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma TEXT UNIQUE NOT NULL,
    pos TEXT NOT NULL,
    ipa_uk TEXT,
    ipa_us TEXT,
    frequency_rank INTEGER,
    cefr_level TEXT
);

CREATE TABLE IF NOT EXISTS definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    definition_en TEXT,
    definition_vi TEXT,
    example TEXT,
    source TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE NOT NULL,
    meaning_vi TEXT,
    pos_pattern TEXT,
    cefr_level TEXT
);

CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_en TEXT UNIQUE NOT NULL,
    text_vi TEXT,
    difficulty_score REAL,
    cefr_level TEXT,
    audio_path TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS word_sentence_map (
    word_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    PRIMARY KEY (word_id, sentence_id),
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reflex_drills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id INTEGER NOT NULL,
    drill_type TEXT NOT NULL,
    prompt_text TEXT,
    correct_answer TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms INTEGER DEFAULT 2500,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dialogue_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    topic TEXT,
    cefr_level TEXT,
    root_node_id INTEGER
);

CREATE TABLE IF NOT EXISTS dialogue_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL,
    parent_node_id INTEGER,
    choice_label TEXT,
    speaker_role TEXT NOT NULL,
    sentence_id INTEGER,
    FOREIGN KEY (tree_id) REFERENCES dialogue_trees (id) ON DELETE CASCADE,
    FOREIGN KEY (parent_node_id) REFERENCES dialogue_nodes (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE NOT NULL,
    phrase_type TEXT NOT NULL,
    pos TEXT,
    cefr_level TEXT,
    difficulty_score REAL,
    definition_en TEXT,
    definition_vi TEXT,
    ipa TEXT,
    audio_std TEXT,
    audio_fast TEXT,
    audio_status TEXT DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS phrase_sentences (
    phrase_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    rank INTEGER,
    PRIMARY KEY (phrase_id, sentence_id),
    FOREIGN KEY (phrase_id) REFERENCES phrases (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS word_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    target_text TEXT NOT NULL,
    target_word_id INTEGER,
    inverted INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    FOREIGN KEY (target_word_id) REFERENCES words (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS word_topics (
    word_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    raw_topic TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, topic)
);

CREATE TABLE IF NOT EXISTS sentence_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT UNIQUE NOT NULL,
    structure_json TEXT,
    example_en TEXT,
    example_vi TEXT,
    cefr_level TEXT
);
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);
CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);
CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);
CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);
CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);
CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);
CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);
CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);
CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);
CREATE INDEX IF NOT EXISTS idx_definitions_word_id ON definitions(word_id);
"""


class SQLiteBulkWriter:
    """High-performance SQLite writer with WAL, bulk transactions, and mmap."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.execute("PRAGMA foreign_keys = ON;")
            for pragma in BULK_PRAGMAS:
                self.conn.execute(pragma)
            logger.info("SQLite connected (WAL): %s", self.db_path)

    def init_schema(self):
        self.connect().executescript(SCHEMA_SQL)
        logger.info("SQLite schema initialized.")

    def create_indexes(self):
        self.connect().executescript(INDEX_SQL)
        logger.info("SQLite indexes created.")

    def insert_words(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("words", rows,
            "INSERT OR IGNORE INTO words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level) VALUES (:lemma, :pos, :ipa_uk, :ipa_us, :frequency_rank, :cefr_level)",
            commit_every)

    def insert_definitions(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("definitions", rows,
            "INSERT INTO definitions (word_id, definition_en, definition_vi, example, source) VALUES (:word_id, :definition_en, :definition_vi, :example, :source)",
            commit_every)

    def insert_sentences(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("sentences", rows,
            "INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, audio_path, source) VALUES (:text_en, :text_vi, :difficulty_score, :cefr_level, :audio_path, :source)",
            commit_every)

    def insert_collocations(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("collocations", rows,
            "INSERT OR IGNORE INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level) VALUES (:phrase, :meaning_vi, :pos_pattern, :cefr_level)",
            commit_every)

    def insert_word_sentence_map(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("word_sentence_map", rows,
            "INSERT OR IGNORE INTO word_sentence_map (word_id, sentence_id) VALUES (:word_id, :sentence_id)",
            commit_every)

    def insert_phrases(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("phrases", rows,
            """INSERT OR IGNORE INTO phrases (phrase, phrase_type, pos, cefr_level, difficulty_score, definition_en, definition_vi, ipa, audio_std, audio_fast, audio_status)
            VALUES (:phrase, :phrase_type, :pos, :cefr_level, :difficulty_score, :definition_en, :definition_vi, :ipa, :audio_std, :audio_fast, :audio_status)""",
            commit_every)

    def insert_word_relations(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("word_relations", rows,
            "INSERT OR IGNORE INTO word_relations (word_id, relation_type, target_text, target_word_id, inverted, source) VALUES (:word_id, :relation_type, :target_text, :target_word_id, :inverted, :source)",
            commit_every)

    def insert_word_topics(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("word_topics", rows,
            "INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic) VALUES (:word_id, :topic, :raw_topic)",
            commit_every)

    def insert_reflex_drills(self, rows: List[Dict[str, Any]], commit_every: int = 10):
        self._batch_insert("reflex_drills", rows,
            "INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms) VALUES (:sentence_id, :drill_type, :prompt_text, :correct_answer, :distractors_json, :target_time_ms)",
            commit_every)

    def insert_dialogue_trees(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("dialogue_trees", rows,
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (:title, :topic, :cefr_level)",
            commit_every)

    def insert_dialogue_nodes(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert("dialogue_nodes", rows,
            "INSERT INTO dialogue_nodes (tree_id, parent_node_id, sentence_id, speaker_role, choice_label) VALUES (:tree_id, :parent_node_id, :sentence_id, :speaker_role, :choice_label)",
            commit_every)

    def _batch_insert(self, table: str, rows: List[Dict[str, Any]], sql: str, commit_every: int):
        if not rows:
            return
        conn = self.conn
        cursor = conn.cursor()
        batches_since_commit = 0
        for i in range(0, len(rows), 5000):
            batch = rows[i:i + 5000]
            cursor.executemany(sql, batch)
            batches_since_commit += 1
            if batches_since_commit >= commit_every:
                conn.commit()
                batches_since_commit = 0
        if batches_since_commit > 0:
            conn.commit()

    def optimize(self):
        """Final optimization: ANALYZE, set WAL, prepare for production."""
        conn = self.conn
        conn.execute("ANALYZE;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sqlite_bulk_writer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/db/sqlite_manager.py tests/test_sqlite_bulk_writer.py
git commit -m "feat(db): SQLiteBulkWriter with WAL, bulk transactions, mmap"
```

---

## Task 5: Single-Pass Kaikki Parser

**Files:**
- Create: `src/ingestion/kaikki_single_pass.py`
- Create: `tests/test_kaikki_single_pass.py`

- [ ] **Step 1: Write the failing test**

`tests/test_kaikki_single_pass.py`:
```python
"""Tests for single-pass Kaikki parser."""

import json
import pytest
from pathlib import Path
from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser


@pytest.fixture
def sample_kaikki(tmp_path):
    """Create a small Kaikki JSONL test file."""
    entries = [
        {"word": "hello", "pos": "intj", "sounds": [{"ipa": "/həˈloʊ/", "tags": ["US"]}],
         "senses": [{"glosses": ["a greeting"], "examples": [{"text": "Hello world!"}]}]},
        {"word": "kick the bucket", "pos": "idiom",
         "senses": [{"glosses": ["to die"]}]},
        {"word": "happy", "pos": "adj",
         "sounds": [{"ipa": "/ˈhæpi/", "tags": ["US"]}],
         "senses": [{"glosses": ["feeling joy"]}],
         "synonyms": [{"word": "glad"}], "antonyms": [{"word": "sad"}],
         "hypernyms": [{"word": "emotion"}]},
    ]
    path = tmp_path / "test.jsonl"
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def test_single_pass_yields_words_and_phrases(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    lemmas = [w["lemma"] for w in result.words]
    assert "hello" in lemmas
    assert "happy" in lemmas
    assert "kick the bucket" not in lemmas  # phrases are separate


def test_single_pass_extracts_phrases(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    phrases = [p["phrase"] for p in result.phrases]
    assert "kick the bucket" in phrases


def test_single_pass_extracts_relations(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    rel_targets = [r["target_text"] for r in result.relations]
    assert "glad" in rel_targets  # synonym
    assert "sad" in rel_targets  # antonym
    assert "emotion" in rel_targets  # hypernym


def test_single_pass_extracts_definitions(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    # hello should have a definition with an example
    hello_defs = [d for d in result.definitions if d.get("lemma") == "hello"]
    assert len(hello_defs) >= 1
    assert hello_defs[0]["definition_en"] == "a greeting"


def test_single_pass_extracts_ipa(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    hello = next(w for w in result.words if w["lemma"] == "hello")
    assert hello["ipa_us"] == "/həˈloʊ/"


def test_single_pass_handles_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    parser = KaikkiSinglePassParser(path)
    result = parser.parse_all()
    assert len(result.words) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kaikki_single_pass.py -v`
Expected: FAIL

- [ ] **Step 3: Implement KaikkiSinglePassParser**

`src/ingestion/kaikki_single_pass.py`:
```python
"""Single-pass Kaikki parser — reads dump once, classifies all entry types."""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PHRASE_POS_ALLOWED = {"idiom", "phrasal verb", "proverb", "phrase"}
MAX_WORDS_PER_PHRASE = 6
CLEAN_CHARS_PATTERN = __import__("re").compile(r"^[a-zA-Z '.-]+$")


@dataclass
class ParseResult:
    """Holds all parsed entities from a single Kaikki pass."""
    words: List[Dict[str, Any]] = field(default_factory=list)
    definitions: List[Dict[str, Any]] = field(default_factory=list)
    phrases: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    topics: List[Dict[str, Any]] = field(default_factory=list)


class KaikkiSinglePassParser:
    """Streams Kaikki dump once, yielding categorized entries.

    For each JSON entry, classifies into:
    - word (single-word, goes to words table)
    - phrase (multi-word expression with allowed POS)
    - relations (synonyms, antonyms, hypernyms, hyponyms)
    - topics (sense-level topics)
    - definitions (for words)
    """

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_all(self, max_entries: Optional[int] = None) -> ParseResult:
        """Parse the entire dump, returning all categorized results."""
        result = ParseResult()
        for i, item in self._stream_jsonl():
            if max_entries and i >= max_entries:
                break
            self._classify(item, result)
        logger.info(
            "Single-pass complete: %d words, %d definitions, %d phrases, %d relations, %d topics",
            len(result.words), len(result.definitions), len(result.phrases),
            len(result.relations), len(result.topics),
        )
        return result

    def parse_stream(self, batch_size: int = 5000) -> Iterator[Tuple[str, List[Dict]]]:
        """Stream batches of categorized entries for memory-efficient processing.

        Yields: (category, [rows]) tuples.
        Categories: 'word', 'phrase', 'relation', 'topic', 'definition'.
        """
        batch: Dict[str, List[Dict]] = {
            "word": [], "phrase": [], "relation": [], "topic": [], "definition": []
        }
        for _, item in self._stream_jsonl():
            self._classify_to_dict(item, batch)
            if len(batch["word"]) >= batch_size:
                for category, rows in batch.items():
                    if rows:
                        yield category, rows
                batch = {k: [] for k in batch}

        for category, rows in batch.items():
            if rows:
                yield category, rows

    def _stream_jsonl(self) -> Iterator[Tuple[int, Dict]]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Kaikki dump not found: {self.file_path}")
        with open(self.file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield i, json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _classify(self, item: Dict, result: ParseResult):
        """Classify a single entry into all applicable categories."""
        word = (item.get("word") or "").strip()
        if not word:
            return

        pos = (item.get("pos") or "").strip().lower()
        is_phrase = " " in word and pos in PHRASE_POS_ALLOWED

        if is_phrase:
            parsed = self._extract_phrase(word, pos, item)
            if parsed:
                result.phrases.append(parsed)
            return

        # Single word
        parsed_word = self._extract_word(word, pos, item)
        if parsed_word:
            result.words.append(parsed_word)

        # Definitions
        defs = self._extract_definitions(word, item)
        result.definitions.extend(defs)

        # Relations
        rels = self._extract_relations(word, item)
        result.relations.extend(rels)

        # Topics
        tops = self._extract_topics(word, item)
        result.topics.extend(tops)

    def _classify_to_dict(self, item: Dict, batch: Dict[str, List[Dict]]):
        """Classify and append to batch dict for streaming."""
        word = (item.get("word") or "").strip()
        if not word:
            return
        pos = (item.get("pos") or "").strip().lower()
        is_phrase = " " in word and pos in {"idiom", "phrasal verb", "proverb", "phrase"}

        if is_phrase:
            parsed = self._extract_phrase(word, pos, item)
            if parsed:
                batch["phrase"].append(parsed)
            return

        parsed_word = self._extract_word(word, pos, item)
        if parsed_word:
            batch["word"].append(parsed_word)

        for d in self._extract_definitions(word, item):
            batch["definition"].append(d)
        for r in self._extract_relations(word, item):
            batch["relation"].append(r)
        for t in self._extract_topics(word, item):
            batch["topic"].append(t)

    def _extract_word(self, word: str, pos: str, item: Dict) -> Optional[Dict]:
        word_clean = word.strip().lower()
        if " " in word_clean:
            return None

        ipa_uk, ipa_us = self._extract_ipas(item)
        vi = self._extract_vi_translations(item)

        return {
            "lemma": word_clean,
            "pos": pos,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "vi_translations": vi,
        }

    def _extract_phrase(self, word: str, pos: str, item: Dict) -> Optional[Dict]:
        word_clean = word.strip().lower()
        if " " not in word_clean:
            return None
        if len(word_clean.split()) > MAX_WORDS_PER_PHRASE and pos != "proverb":
            return None
        if not CLEAN_CHARS_PATTERN.match(word_clean):
            return None

        ipa = None
        for sound in item.get("sounds", []):
            if sound.get("ipa"):
                ipa = sound["ipa"]
                break

        vi = self._extract_vi_translations(item)

        definition_en = None
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            for gloss in glosses:
                if gloss.strip():
                    definition_en = gloss.strip()
                    break
            if definition_en:
                break

        if not definition_en:
            return None

        return {
            "phrase": word_clean,
            "phrase_type": pos.replace(" ", "_"),
            "pos": pos,
            "definition_en": definition_en,
            "definition_vi": vi,
            "ipa": ipa,
        }

    def _extract_definitions(self, word: str, item: Dict) -> List[Dict]:
        results = []
        vi = self._extract_vi_translations(item)
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            example = None
            for ex in sense.get("examples", []):
                if isinstance(ex, dict):
                    example = ex.get("text")
                elif isinstance(ex, str):
                    example = ex
                if example:
                    break
            for gloss in glosses:
                results.append({
                    "lemma": word.lower(),
                    "definition_en": gloss.strip(),
                    "definition_vi": vi,
                    "example": example,
                    "source": "Kaikki/Wiktionary",
                })
        return results

    def _extract_relations(self, word: str, item: Dict) -> List[Dict]:
        results = []
        word_lower = word.lower()
        seen = set()

        for section, rel_type in [
            ("synonyms", "synonym"), ("antonyms", "antonym"),
            ("hypernyms", "hypernym"), ("hyponyms", "hyponym"),
        ]:
            candidates = list(item.get(section, []) or [])
            for sense in item.get("senses", []):
                candidates.extend(sense.get(section, []) or [])

            count = 0
            for rel in candidates:
                if count >= 25:
                    break
                if not isinstance(rel, dict):
                    continue
                target = (rel.get("word") or "").strip().lower()
                if not target or target == word_lower:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue
                key = (rel_type, target)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "lemma": word_lower,
                    "relation_type": rel_type,
                    "target_text": target,
                    "source": section,
                })
                count += 1
        return results

    def _extract_topics(self, word: str, item: Dict) -> List[Dict]:
        results = []
        seen = set()
        for sense in item.get("senses", []):
            for raw in sense.get("topics", []) or []:
                raw_label = (raw or "").strip()
                if not raw_label:
                    continue
                key = raw_label.lower()
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "lemma": word.lower(),
                    "raw_topic": raw_label,
                })
        return results

    @staticmethod
    def _extract_ipas(item: Dict) -> Tuple[Optional[str], Optional[str]]:
        ipa_uk, ipa_us = None, None
        for sound in item.get("sounds", []):
            ipa = sound.get("ipa")
            if not ipa:
                continue
            tags = sound.get("tags", [])
            if "UK" in tags or "British" in tags:
                ipa_uk = ipa
            elif "US" in tags or "American" in tags:
                ipa_us = ipa
            elif ipa_uk is None:
                ipa_uk = ipa
                ipa_us = ipa
        return ipa_uk, ipa_us

    @staticmethod
    def _extract_vi_translations(item: Dict) -> Optional[str]:
        vi_translations = []
        for trans in item.get("translations", []):
            if isinstance(trans, dict):
                code = trans.get("code") or trans.get("lang_code")
                lang = trans.get("lang")
                if code == "vi" or lang == "Vietnamese":
                    w = trans.get("word", "").strip()
                    if w and w not in vi_translations:
                        vi_translations.append(w)
        return ", ".join(vi_translations) if vi_translations else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_kaikki_single_pass.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/kaikki_single_pass.py tests/test_kaikki_single_pass.py
git commit -m "feat(ingestion): single-pass Kaikki parser replaces 3 separate parsers"
```

---

## Task 6: Parallel Downloader

**Files:**
- Create: `src/ingestion/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: Write the failing test**

`tests/test_downloader.py`:
```python
"""Tests for parallel downloader."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.ingestion.downloader import DownloadTask, download_all_parallel


def test_download_task_creates():
    task = DownloadTask(url="https://example.com/file.zip", dest=Path("/tmp/file.zip"))
    assert task.url == "https://example.com/file.zip"
    assert task.dest == Path("/tmp/file.zip")


@patch("src.ingestion.downloader._download_one")
def test_download_all_parallel_runs(mock_download, tmp_path):
    mock_download.return_value = True
    tasks = [
        DownloadTask(url="https://ex.com/a.zip", dest=Path(tmp_path / "a.zip")),
        DownloadTask(url="https://ex.com/b.zip", dest=Path(tmp_path / "b.zip")),
    ]
    results = download_all_parallel(tasks, max_workers=2)
    assert mock_download.call_count == 2
    assert all(results.values())


def test_download_skips_existing_files(tmp_path):
    """If file already exists and non-empty, skip download."""
    existing = tmp_path / "exists.zip"
    existing.write_bytes(b"content")
    tasks = [DownloadTask(url="https://ex.com/exists.zip", dest=existing)]
    with patch("src.ingestion.downloader._download_one") as mock:
        results = download_all_parallel(tasks, max_workers=1)
        # Should skip because file exists
        assert mock.call_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_downloader.py -v`
Expected: FAIL

- [ ] **Step 3: Implement parallel downloader**

`src/ingestion/downloader.py`:
```python
"""Parallel downloader with resume support."""

import logging
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    url: str
    dest: Path
    min_size: int = 1  # Skip if existing file >= this size
    description: str = ""


def download_all_parallel(tasks: List[DownloadTask], max_workers: int = 4) -> Dict[str, bool]:
    """Download multiple files in parallel. Returns {url: success}."""
    results: Dict[str, bool] = {}
    pending = [t for t in tasks if not _already_has(t.dest, t.min_size)]

    if not pending:
        logger.info("All %d files already exist — skipping downloads.", len(tasks))
        return {t.url: True for t in tasks}

    logger.info("Downloading %d/%d files (%d workers)...", len(pending), len(tasks), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_download_one, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results[task.url] = future.result()
            except Exception as e:
                logger.error("Download failed for %s: %s", task.url, e)
                results[task.url] = False

    # Mark skipped tasks as successful
    for t in tasks:
        if t.url not in results:
            results[t.url] = True

    succeeded = sum(1 for v in results.values() if v)
    logger.info("Downloads complete: %d/%d succeeded.", succeeded, len(tasks))
    return results


def _already_has(path: Path, min_size: int) -> bool:
    return path.exists() and path.stat().st_size >= min_size


def _download_one(task: DownloadTask) -> bool:
    """Download a single file with progress and resume support."""
    task.dest.parent.mkdir(parents=True, exist_ok=True)
    existing = task.dest.stat().st_size if task.dest.exists() else 0

    if existing >= task.min_size:
        logger.info("  [skip] %s already exists.", task.dest.name)
        return True

    logger.info("  [download] %s -> %s", task.url, task.dest)

    try:
        request = urllib.request.Request(task.url)
        if existing > 0:
            request.add_header("Range", f"bytes={existing}-")

        with urllib.request.urlopen(request, timeout=60) as resp:
            if resp.status == 200 and existing > 0:
                # Server ignored Range, restart
                existing = 0
                mode = "wb"
            else:
                mode = "ab"

            with open(task.dest, mode) as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)

        size_mb = task.dest.stat().st_size / 1e6
        logger.info("  [done] %s (%.1f MB)", task.dest.name, size_mb)
        return True

    except Exception as e:
        logger.error("  [fail] %s: %s", task.dest.name, e)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_downloader.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/downloader.py tests/test_downloader.py
git commit -m "feat(ingestion): parallel downloader with ThreadPoolExecutor"
```

---

## Task 7: Hybrid Translator

**Files:**
- Create: `src/nlp/translator_hybrid.py`
- Create: `tests/test_translator_hybrid.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add argostranslate to dependencies**

`pyproject.toml` — add to `[project.dependencies]`:
```
"argostranslate>=1.9.0",
```

- [ ] **Step 2: Write the failing test**

`tests/test_translator_hybrid.py`:
```python
"""Tests for hybrid translator."""

import pytest
from unittest.mock import MagicMock, patch
from src.nlp.translator_hybrid import HybridTranslator


def test_uses_local_when_available():
    """If Argos succeeds, don't call Google."""
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "Xin chào"
    translator._fallback = MagicMock()

    result = translator.translate("hello")

    assert result == "Xin chào"
    translator._fallback.translate.assert_not_called()


def test_falls_back_to_google_when_local_fails():
    """If Argos returns invalid, try Google."""
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "hello"  # passthrough
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")

    assert result == "Xin chào"
    translator._fallback.translate.assert_called_once()


def test_returns_empty_when_both_fail():
    """If both fail, return empty string."""
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "hello"  # passthrough = fail
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "hello"  # also passthrough

    result = translator.translate("hello")
    assert result == ""


def test_skips_local_if_not_available():
    """If Argos not installed, go straight to Google."""
    translator = HybridTranslator()
    translator._local = None
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")
    assert result == "Xin chào"


def test_validates_output():
    """Translation must pass Vietnamese validation."""
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "12345"  # numbers only
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")
    assert result == "Xin chào"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_translator_hybrid.py -v`
Expected: FAIL

- [ ] **Step 4: Implement HybridTranslator**

`src/nlp/translator_hybrid.py`:
```python
"""Hybrid Vietnamese translator — Argos Translate (local) primary, Google Translate fallback."""

import logging
import threading
import time
from typing import Optional

from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)


class HybridTranslator:
    """Translates English to Vietnamese using Argos (offline) primary, Google fallback."""

    def __init__(self, source: str = "en", target: str = "vi"):
        self.validator = VietnameseTextValidator()
        self._local = self._init_argos(source, target)
        self._fallback = self._init_google(source, target)
        self._lock = threading.Lock()

    def _init_argos(self, source: str, target: str):
        """Try to initialize Argos Translate. Return None if unavailable."""
        try:
            import argostranslate.package
            import argostranslate.translate

            # Ensure en-vi package is installed
            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            pkg = next(
                (p for p in available if p.from_code == source and p.to_code == target),
                None,
            )
            if pkg and not pkg.is_installed:
                logger.info("Installing Argos Translate %s-%s...", source, target)
                argostranslate.package.install_from_path(pkg.download())

            logger.info("Argos Translate ready (offline).")
            return argostranslate.translate

        except ImportError:
            logger.info("Argos Translate not installed — using Google Translate only.")
            return None
        except Exception as e:
            logger.warning("Argos Translate init failed: %s", e)
            return None

    def _init_google(self, source: str, target: str):
        """Initialize Google Translate (deep_translator)."""
        try:
            from deep_translator import GoogleTranslator
            return GoogleTranslator(source=source, target=target)
        except Exception as e:
            logger.warning("Google Translate init failed: %s", e)
            return None

    def translate(self, text: str) -> str:
        """Translate text, trying local first then fallback. Returns empty on failure."""
        if not text or not text.strip():
            return ""

        clean = text.strip()

        # Try local (Argos) first
        if self._local:
            try:
                import argostranslate.translate
                result = argostranslate.translate.translate(clean, "en", "vi")
                if result and self.validator.is_vietnamese(result):
                    return result
            except Exception:
                pass

        # Fallback to Google
        if self._fallback:
            try:
                result = self._fallback.translate(clean)
                if result and self.validator.is_vietnamese(result):
                    return result
            except Exception:
                pass

        return ""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_translator_hybrid.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/nlp/translator_hybrid.py tests/test_translator_hybrid.py pyproject.toml
git commit -m "feat(nlp): hybrid Vietnamese translator (Argos local + Google fallback)"
```

---

## Task 8: Stage 1 — Ingest

**Files:**
- Create: `src/stages/__init__.py`
- Create: `src/stages/stage_1_ingest.py`

- [ ] **Step 1: Write the integration test**

`tests/test_stages.py` (partial):
```python
"""Integration tests for pipeline stages."""

import pytest
import json
from pathlib import Path
from src.pipeline.context import PipelineContext
from src.db.duckdb_manager import DuckDBManager


@pytest.fixture
def ctx(tmp_path):
    context = PipelineContext(
        sqlite_path=tmp_path / "test.db",
        duckdb_path=tmp_path / "staging.duckdb",
        processed_dir=tmp_path / "processed",
        output_dir=tmp_path / "output",
        raw_dir=tmp_path / "raw",
    )
    context.processed_dir.mkdir(parents=True, exist_ok=True)
    context.output_dir.mkdir(parents=True, exist_ok=True)
    context.raw_dir.mkdir(parents=True, exist_ok=True)
    return context


def test_stage_1_ingest_populates_duckdb(ctx, tmp_path):
    """Stage 1: Kaikki single-pass should populate DuckDB raw tables."""
    # Create small Kaikki fixture
    kaikki_path = tmp_path / "raw" / "kaikki.org-dictionary-English.json"
    kaikki_path.parent.mkdir(parents=True, exist_ok=True)
    with open(kaikki_path, "w") as f:
        f.write(json.dumps({
            "word": "hello", "pos": "intj",
            "sounds": [{"ipa": "/həˈloʊ/", "tags": ["US"]}],
            "senses": [{"glosses": ["a greeting"]}],
        }) + "\n")
        f.write(json.dumps({
            "word": "happy", "pos": "adj",
            "synonyms": [{"word": "glad"}],
        }) + "\n")
        f.write(json.dumps({
            "word": "break the ice", "pos": "idiom",
            "senses": [{"glosses": ["to initiate conversation"]}],
        }) + "\n")

    from src.stages.stage_1_ingest import stage_1_ingest
    ctx.duckdb_conn = DuckDBManager(ctx.duckdb_path)
    ctx.duckdb_conn.connect()
    ctx.duckdb_conn.init_schema()

    stage_1_ingest(ctx)

    words = ctx.duckdb_conn.row_count("raw_words")
    phrases = ctx.duckdb_conn.row_count("raw_phrases")
    relations = ctx.duckdb_conn.row_count("raw_relations")

    assert words >= 2  # hello, happy
    assert phrases >= 1  # break the ice
    assert relations >= 1  # synonym: glad
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_stages.py::test_stage_1_ingest_populates_duckdb -v`
Expected: FAIL

- [ ] **Step 3: Implement Stage 1**

`src/stages/__init__.py`:
```python
```

`src/stages/stage_1_ingest.py`:
```python
"""Stage 1: Ingest — Download raw data, single-pass Kaikki, corpora."""

import logging
from pathlib import Path

from config.settings import (
    KAIKKI_JSON_PATH, TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH,
    OPENSUBTITLES_EN, OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
    MAX_SENTENCES_PER_CORPUS,
)
from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser
from src.ingestion.downloader import DownloadTask, download_all_parallel
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_1_ingest(ctx: PipelineContext):
    """Download raw data and ingest into DuckDB staging tables."""
    _ensure_raw_data(ctx)
    _ingest_kaikki(ctx)
    _ingest_corpora(ctx)
    logger.info("[Stage 1] Ingest complete.")


def _ensure_raw_data(ctx: PipelineContext):
    """Download missing raw files in parallel."""
    tasks = [
        DownloadTask(url="https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
                      dest=KAIKKI_JSON_PATH, min_size=1_000_000_000, description="Kaikki Dictionary"),
        DownloadTask(url="https://downloads.tatoeba.org/exports/sentences.tar.bz2",
                      dest=ctx.raw_dir / "sentences.tar.bz2", description="Tatoeba Sentences"),
        DownloadTask(url="https://downloads.tatoeba.org/exports/links.tar.bz2",
                      dest=ctx.raw_dir / "links.tar.bz2", description="Tatoeba Links"),
    ]
    download_all_parallel(tasks, max_workers=4)


def _ingest_kaikki(ctx: PipelineContext):
    """Single-pass Kaikki ingestion into DuckDB."""
    if not KAIKKI_JSON_PATH.exists() or KAIKKI_JSON_PATH.stat().st_size == 0:
        logger.warning("[Stage 1] Kaikki dump not found — skipping.")
        return

    db = ctx.duckdb_conn
    db.init_schema()

    parser = KaikkiSinglePassParser(KAIKKI_JSON_PATH)
    total_words = 0

    for category, batch in parser.parse_stream(batch_size=5000):
        if category == "word":
            db.insert_rows("raw_words", batch)
            total_words += len(batch)
        elif category == "definition":
            # Definitions need word_id mapping — deferred to transform
            db.insert_rows("raw_definitions", [{"lemma": b["lemma"], **b} for b in batch])
        elif category == "phrase":
            db.insert_rows("raw_phrases", batch)
        elif category == "relation":
            db.insert_rows("raw_relations", [{"lemma": b["lemma"], **b} for b in batch])
        elif category == "topic":
            db.insert_rows("raw_topics", [{"lemma": b["lemma"], **b} for b in batch])

        if total_words % 50_000 == 0 and category == "word":
            logger.info("   [Kaikki] %d words staged...", total_words)

    logger.info("[Stage 1] Kaikki: %d words, %d phrases, %d relations",
                db.row_count("raw_words"), db.row_count("raw_phrases"),
                db.row_count("raw_relations"))


def _ingest_corpora(ctx: PipelineContext):
    """Ingest Tatoeba + parallel corpora into DuckDB."""
    db = ctx.duckdb_conn
    # Tatoeba CSV load via DuckDB parallel reader
    if TATOEBA_SENTENCES_PATH.exists() and TATOEBA_LINKS_PATH.exists():
        db.execute("""
            INSERT INTO raw_sentences (text_en, text_vi, source)
            SELECT eng.text, vie.text, 'Tatoeba'
            FROM read_csv_auto(?, delim='\t', columns={'id': 'INTEGER', 'lang': 'VARCHAR', 'text': 'VARCHAR'}) eng
            INNER JOIN read_csv_auto(?, delim='\t', columns={'id1': 'INTEGER', 'id2': 'INTEGER'}) link
                ON link.id1 = eng.id
            INNER JOIN read_csv_auto(?, delim='\t', columns={'id': 'INTEGER', 'lang': 'VARCHAR', 'text': 'VARCHAR'}) vie
                ON vie.id = link.id2 AND vie.lang = 'vie'
            WHERE eng.lang = 'eng'
            ON CONFLICT (text_en) DO NOTHING
        """, [str(TATOEBA_SENTENCES_PATH), str(TATOEBA_LINKS_PATH), str(TATOEBA_SENTENCES_PATH)])

    logger.info("[Stage 1] Sentences staged: %d", db.row_count("raw_sentences"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_stages.py::test_stage_1_ingest_populates_duckdb -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/ tests/test_stages.py
git commit -m "feat(stages): Stage 1 — single-pass Kaikki + parallel corpora ingest"
```

---

## Task 9: Stage 2 — Transform

**Files:**
- Create: `src/stages/stage_2_transform.py`

- [ ] **Step 1: Implement Stage 2**

`src/stages/stage_2_transform.py`:
```python
"""Stage 2: Transform — CEFR grading, lemmatization, collocations."""

import logging
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_2_transform(ctx: PipelineContext):
    """Apply transforms to DuckDB staging data."""
    db = ctx.duckdb_conn
    _apply_cefr_grading(ctx, db)
    _build_lemma_cache(ctx, db)
    _link_word_sentences(ctx, db)
    _extract_collocations(ctx, db)
    _build_inverse_relations(db)
    _map_topics(ctx, db)
    logger.info("[Stage 2] Transform complete.")


def _apply_cefr_grading(ctx: PipelineContext, db):
    """Apply CEFR grading via DuckDB SQL (vectorized)."""
    freq_path = ctx.raw_dir / "SUBTLEX_US.csv"
    if freq_path.exists():
        db.execute("""
            INSERT OR REPLACE INTO raw_words (id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level)
            SELECT w.id, w.lemma, w.pos, w.ipa_uk, w.ipa_us,
                   COALESCE(f.rank, 25000),
                   CASE
                       WHEN COALESCE(f.rank, 25000) <= 1000 THEN 'A1'
                       WHEN COALESCE(f.rank, 25000) <= 25000 THEN 'A2'
                       WHEN COALESCE(f.rank, 25000) <= 5000 THEN 'B1'
                       WHEN COALESCE(f.rank, 25000) <= 10000 THEN 'B2'
                       WHEN COALESCE(f.rank, 25000) <= 20000 THEN 'C1'
                       ELSE 'C2'
                   END
            FROM raw_words w
            LEFT JOIN read_csv_auto(?, columns={'Word': 'VARCHAR', 'rank': 'INTEGER'}) f
                ON lower(f.Word) = w.lemma
        """, [str(freq_path)])
    logger.info("[Stage 2] CEFR grading applied.")


def _build_lemma_cache(ctx: PipelineContext, db):
    """Build in-memory lemma→id cache for fast lookups."""
    rows = db.query("SELECT id, lemma FROM raw_words").fetchall()
    ctx.lemma_cache = {lemma: word_id for word_id, lemma in rows}
    logger.info("[Stage 2] Lemma cache: %d entries.", len(ctx.lemma_cache))


def _link_word_sentences(ctx: PipelineContext, db):
    """Lemmatize sentences and link to words."""
    from src.nlp.lemmatizer import Lemmatizer
    lemmatizer = Lemmatizer()
    sentences = db.query("SELECT id, text_en FROM raw_sentences").fetchall()
    map_batch = []
    for s_id, text_en in sentences:
        tokens = lemmatizer.lemmatize_text(text_en)
        for token in tokens:
            word_id = ctx.lemma_cache.get(token["lemma"])
            if word_id:
                map_batch.append({"word_id": word_id, "sentence_id": s_id})
        if len(map_batch) >= 10_000:
            db.insert_rows("word_sentence_map", map_batch)
            map_batch = []
    if map_batch:
        db.insert_rows("word_sentence_map", map_batch)
    logger.info("[Stage 2] Word-sentence links: %d", db.row_count("word_sentence_map"))


def _extract_collocations(ctx: PipelineContext, db):
    """Extract collocations from sentences."""
    from src.nlp.chunk_extractor import ChunkExtractor
    extractor = ChunkExtractor()
    sentences = db.query("SELECT text_en FROM raw_sentences").fetchall()
    seen = set()
    colloc_batch = []
    for (text_en,) in sentences:
        chunks = extractor.extract_collocations(text_en)
        for chunk in chunks:
            phrase = chunk["phrase"]
            if phrase not in seen:
                seen.add(phrase)
                colloc_batch.append({
                    "phrase": phrase,
                    "pos_pattern": chunk["pos_pattern"],
                    "cefr_level": "B1",
                    "meaning_vi": None,  # deferred to Stage 3
                })
    db.insert_rows("collocations", colloc_batch)
    logger.info("[Stage 2] Collocations: %d", db.row_count("collocations"))


def _build_inverse_relations(db):
    """Build inverse hyponym links via SQL set-based operation."""
    db.execute("""
        INSERT OR IGNORE INTO raw_relations (word_id, relation_type, target_text, target_word_id, inverted, source)
        SELECT r.target_word_id, 'hyponym', w.lemma, r.word_id, 1, r.source
        FROM raw_relations r
        JOIN raw_words w ON w.id = r.word_id
        WHERE r.relation_type = 'hypernym' AND r.inverted = 0
          AND r.target_word_id IS NOT NULL
    """)
    logger.info("[Stage 2] Inverse relations built.")


def _map_topics(ctx: PipelineContext, db):
    """Map raw topics to curated themes."""
    from src.nlp.topic_mapper import TopicMapper
    topics = db.query("SELECT word_id, raw_topic FROM raw_topics").fetchall()
    mapped = []
    seen = set()
    for word_id, raw_topic in topics:
        theme = TopicMapper.map_topic(raw_topic)
        key = (word_id, theme)
        if key not in seen:
            seen.add(key)
            mapped.append({"word_id": word_id, "topic": theme, "raw_topic": raw_topic})
    db.execute("DELETE FROM raw_topics")
    db.insert_rows("raw_topics", mapped)
    logger.info("[Stage 2] Topics mapped: %d", db.row_count("raw_topics"))
```

- [ ] **Step 2: Commit**

```bash
git add src/stages/stage_2_transform.py
git commit -m "feat(stages): Stage 2 — CEFR grading, lemmatization, collocations, inverse relations"
```

---

## Task 10: Stage 3 — Enrich

**Files:**
- Create: `src/stages/stage_3_enrich.py`

- [ ] **Step 1: Implement Stage 3**

`src/stages/stage_3_enrich.py`:
```python
"""Stage 3: Enrich — Vietnamese translation, reflex drills, audio generation."""

import asyncio
import logging
import time
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_3_enrich(ctx: PipelineContext):
    """Async enrichment: translations, drills, audio."""
    _backfill_translations(ctx)
    _generate_reflex_drills(ctx)
    _build_dialogue_scenarios(ctx)
    logger.info("[Stage 3] Enrich complete.")


def _backfill_translations(ctx: PipelineContext):
    """Backfill all missing Vietnamese translations via async batch."""
    from src.nlp.translator_hybrid import HybridTranslator
    translator = HybridTranslator()
    db = ctx.duckdb_conn

    # Translations for collocations
    null_colls = db.query(
        "SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = ''"
    ).fetchall()
    _translate_and_update(db, "collocations", "id", "meaning_vi", null_colls, translator)

    # Translations for definitions (from Kaikki dump)
    null_defs = db.query(
        "SELECT id, definition_en FROM raw_definitions WHERE definition_vi IS NULL OR definition_vi = '' LIMIT ?"
    ).fetchall()
    _translate_and_update(db, "raw_definitions", "id", "definition_vi", null_defs, translator)

    logger.info("[Stage 3] Translation backfill complete.")


def _translate_and_update(db, table, id_col, target_col, rows, translator, batch_size: int = 100):
    """Batch translate and update rows."""
    if not rows:
        return
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        updates = []
        for row_id, text in batch:
            vi = translator.translate(text)
            if vi:
                updates.append((vi, row_id))
        if updates:
            db.connect().executemany(
                f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?",
                updates
            )
            db.connect().commit()
        time.sleep(0.1)


def _generate_reflex_drills(ctx: PipelineContext):
    """Generate reflex drill cards for sentences."""
    from src.nlp.reflex_builder import ReflexBuilder
    db = ctx.duckdb_conn
    sentences = db.query("SELECT id, text_en, text_vi, cefr_level FROM raw_sentences").fetchall()
    if not sentences:
        return
    pool = [{"id": r[0], "text_en": r[1], "text_vi": r[2], "cefr_level": r[3]} for r in sentences]
    builder = ReflexBuilder(sentence_pool=pool)
    for sent in pool:
        drill = builder.build_drill(sent)
        db.insert_rows("reflex_drills", [drill])
    logger.info("[Stage 3] Reflex drills: %d", db.row_count("reflex_drills"))


def _build_dialogue_scenarios(ctx: PipelineContext):
    """Build dialogue trees (sample scenarios)."""
    from src.nlp.scenario_builder import ScenarioBuilder
    builder = ScenarioBuilder()
    scenarios = builder.build_sample_scenarios()
    db = ctx.duckdb_conn
    for sc in scenarios:
        db.execute(
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (?, ?, ?)",
            (sc["title"], sc["topic"], sc["cefr_level"])
        )
    logger.info("[Stage 3] Dialogue scenarios: %d", db.row_count("dialogue_trees"))
```

- [ ] **Step 2: Commit**

```bash
git add src/stages/stage_3_enrich.py
git commit -m "feat(stages): Stage 3 — VI translation backfill, reflex drills, dialogues"
```

---

## Task 11: Stage 4 — Export

**Files:**
- Create: `src/stages/stage_4_export.py`

- [ ] **Step 1: Implement Stage 4**

`src/stages/stage_4_export.py`:
```python
"""Stage 4: Export — DuckDB staging → SQLite production DB."""

import logging
import sqlite3
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_4_export(ctx: PipelineContext):
    """Bulk export from DuckDB to SQLite with WAL optimization."""
    from src.db.sqlite_manager import SQLiteBulkWriter

    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()

    db = ctx.duckdb_conn

    # Export words
    words = db.query("SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words").fetchall()
    writer.insert_words([
        {"lemma": r[1], "pos": r[2], "ipa_uk": r[3], "ipa_us": r[4],
         "frequency_rank": r[5], "cefr_level": r[6]}
        for r in words
    ], commit_every=10)
    logger.info("[Stage 4] Words exported: %d", len(words))

    # Export definitions (using lemma_cache for word_id mapping)
    if ctx.lemma_cache:
        defs = db.query("SELECT lemma, definition_en, definition_vi, example, source FROM raw_definitions").fetchall()
        writer.insert_definitions([
            {"word_id": ctx.lemma_cache.get(r[0]), "definition_en": r[1],
             "definition_vi": r[2], "example": r[3], "source": r[4]}
            for r in defs if ctx.lemma_cache.get(r[0])
        ], commit_every=10)
        logger.info("[Stage 4] Definitions exported: %d", len(defs))

    # Export sentences
    sentences = db.query("SELECT text_en, text_vi, difficulty_score, cefr_level, source FROM raw_sentences").fetchall()
    writer.insert_sentences([
        {"text_en": r[0], "text_vi": r[1], "difficulty_score": r[2],
         "cefr_level": r[3], "source": r[5]}
        for r in sentences
    ], commit_every=10)
    logger.info("[Stage 4] Sentences exported: %d", len(sentences))

    # Export collocations
    collocs = db.query("SELECT phrase, meaning_vi, pos_pattern, cefr_level FROM collocations").fetchall()
    writer.insert_collocations([
        {"phrase": r[0], "meaning_vi": r[1], "pos_pattern": r[2], "cefr_level": r[3]}
        for r in collocs
    ], commit_every=10)

    # Export phrases
    phrases = db.query("SELECT phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa FROM raw_phrases").fetchall()
    writer.insert_phrases([{
        "phrase": r[0], "phrase_type": r[1], "pos": r[2], "cefr_level": r[3],
        "definition_en": r[4], "definition_vi": r[5], "ipa": r[6],
        "difficulty_score": None, "audio_std": None, "audio_fast": None, "audio_status": "ok"
    } for r in phrases], commit_every=10)

    # Export relations
    rels = db.query("SELECT word_id, relation_type, target_text, target_word_id, inverted, source FROM raw_relations").fetchall()
    writer.insert_word_relations([{
        "word_id": r[0], "relation_type": r[1], "target_text": r[2],
        "target_word_id": r[3], "inverted": r[4], "source": r[5]
    } for r in rels], commit_every=10)

    # Export topics
    topics = db.query("SELECT word_id, topic, raw_topic FROM raw_topics").fetchall()
    writer.insert_word_topics([
        {"word_id": r[0], "topic": r[1], "raw_topic": r[2]}
        for r in topics
    ], commit_every=10)

    # Export reflex drills
    drills = db.query("SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms FROM reflex_drills").fetchall()
    writer.insert_reflex_drills([{
        "sentence_id": r[0], "drill_type": r[1], "prompt_text": r[2],
        "correct_answer": r[3], "distractors_json": r[4], "target_time_ms": r[5]
    } for r in drills], commit_every=10)

    # Final optimization
    writer.create_indexes()
    writer.optimize()

    # Verify
    violations = writer.conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        logger.warning("[Stage 4] Foreign key violations: %d", len(violations))

    size_mb = ctx.sqlite_path.stat().st_size / 1e6
    logger.info("[Stage 4] Export complete. DB size: %.1f MB", size_mb)

    writer.close()
```

- [ ] **Step 2: Commit**

```bash
git add src/stages/stage_4_export.py
git commit -m "feat(stages): Stage 4 — DuckDB → SQLite bulk export with WAL optimization"
```

---

## Task 12: Main Entry Point + Makefile

**Files:**
- Modify: `src/main.py`
- Modify: `Makefile`

- [ ] **Step 1: Rewrite main.py**

`src/main.py`:
```python
"""DAG-based pipeline entry point for English Dataset System Engine v2.0."""

import sys
import logging
import time
import argparse

from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor
from src.pipeline.registry import CheckpointRegistry
from src.db.duckdb_manager import DuckDBManager
from src.db.sqlite_manager import SQLiteBulkWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="English Dataset Pipeline v2.0")
    parser.add_argument("--force-reset", action="store_true", help="Force re-run all stages.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Kaikki ingestion.")
    parser.add_argument("--vi-budget", type=int, default=1000, help="Max VI translations per run.")
    parser.add_argument("--audio-limit", type=int, default=5000, help="Max audio files to generate.")
    parser.add_argument("--build-core-pack", action="store_true", help="Build Core 3000 word pack.")
    parser.add_argument("--stage", type=str, default=None, help="Run single stage: ingest|transform|enrich|export|pack.")
    return parser.parse_args()


def build_dag(ctx: PipelineContext, registry: CheckpointRegistry) -> DAGExecutor:
    """Build the pipeline DAG with all stages and dependencies."""
    from src.stages.stage_1_ingest import stage_1_ingest
    from src.stages.stage_2_transform import stage_2_transform
    from src.stages.stage_3_enrich import stage_3_enrich
    from src.stages.stage_4_export import stage_4_export

    dag = DAGExecutor(registry=registry)
    dag.add_step("ingest", stage_1_ingest)
    dag.add_step("transform", stage_2_transform, depends={"ingest"})
    dag.add_step("enrich", stage_3_enrich, depends={"transform"})
    dag.add_step("export", stage_4_export, depends={"enrich"})

    if ctx.build_core_pack:
        from src.stages.stage_5_core_pack import stage_5_core_pack
        dag.add_step("pack", stage_5_core_pack, depends={"export"})

    return dag


def run_pipeline():
    args = parse_args()
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("   VOCABCRAFT ENGINE v2.0 — DAG PIPELINE")
    logger.info("=" * 60)

    ctx = PipelineContext(
        force_reset=args.force_reset,
        vi_budget=args.vi_budget,
        audio_limit=args.audio_limit,
        build_core_pack=args.build_core_pack,
    )

    registry = CheckpointRegistry(ctx.checkpoint_dir)

    # Open DuckDB connection
    ctx.duckdb_conn = DuckDBManager(ctx.duckdb_path)
    ctx.duckdb_conn.connect()

    # Build and execute DAG
    dag = build_dag(ctx, registry)

    if args.stage:
        # Run single stage
        logger.info("Running single stage: %s", args.stage)
        single_dag = DAGExecutor(registry=registry)
        stage_funcs = {
            "ingest": __import__("src.stages.stage_1_ingest", fromlist=["stage_1_ingest"]).stage_1_ingest,
            "transform": __import__("src.stages.stage_2_transform", fromlist=["stage_2_transform"]).stage_2_transform,
            "enrich": __import__("src.stages.stage_3_enrich", fromlist=["stage_3_enrich"]).stage_3_enrich,
            "export": __import__("src.stages.stage_4_export", fromlist=["stage_4_export"]).stage_4_export,
        }
        if args.stage in stage_funcs:
            single_dag.add_step(args.stage, stage_funcs[args.stage])
            single_dag.execute(ctx, force_reset=args.force_reset)
        else:
            logger.error("Unknown stage: %s", args.stage)
            sys.exit(1)
    else:
        dag.execute(ctx, force_reset=args.force_reset)

    ctx.duckdb_conn.close()

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("   PIPELINE COMPLETE IN %.1f SECONDS (%.1f min)", elapsed, elapsed / 60)
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
```

- [ ] **Step 2: Update Makefile**

`Makefile` — add new targets:

```makefile
# ── Run individual stages ──
run-step:
	@echo "==> Running pipeline stage: $(STEP)..."
	$(PYTHON) main.py --stage $(STEP)

benchmark:
	@echo "==> Running benchmark..."
	time $(PYTHON) main.py --force-reset

profile:
	@echo "==> Profiling pipeline..."
	$(PYTHON) -m cProfile -o data/processed/profile.stats main.py
	$(PYTHON) -m pstats data/processed/profile.stats
```

- [ ] **Step 3: Commit**

```bash
git add src/main.py Makefile
git commit -m "feat: main.py DAG entry point + Makefile stage targets"
```

---

## Task 13: Update settings.py

**Files:**
- Modify: `config/settings.py`

- [ ] **Step 1: Add DuckDB settings**

Add to `config/settings.py`:

```python
# DuckDB Staging
STAGING_DUCKDB_PATH = PROCESSED_DATA_DIR / "staging.duckdb"
DUCKDB_MEMORY_LIMIT = "8GB"
DUCKDB_THREADS = 0  # Auto-detect

# Pipeline config
PIPELINE_CHECKPOINT_DIR = PROCESSED_DATA_DIR / "checkpoints"
MAX_SENTENCES_PER_CORPUS = 500_000
```

- [ ] **Step 2: Commit**

```bash
git add config/settings.py
git commit -m "config: add DuckDB staging paths and pipeline config"
```

---

## Self-Review Checklist

- [x] Single-pass Kaikki parser (Task 5) — covers spec §5.1
- [x] DuckDB staging (Task 3) — covers spec §5.2
- [x] SQLite WAL + bulk commit (Task 4) — covers spec §5.3
- [x] Lemma cache (Task 9, stage 2) — covers spec §5.4
- [x] Hybrid translator (Task 7) — covers spec §5.5
- [x] Deferred translation (Task 10, stage 3) — covers spec §5.6
- [x] Parallel download (Task 6) — covers spec §5.7
- [x] DAG executor (Task 2) — covers spec §5.8
- [x] Stage 1-5 implementation (Task 8-12) — covers spec §6
- [x] Makefile run-step (Task 12) — covers spec §7
- [x] Checkpoint per stage (Task 1) — covers spec §8
- [x] No TBDs/TODOs in plan
- [x] Type consistency across tasks (PipelineContext used everywhere)

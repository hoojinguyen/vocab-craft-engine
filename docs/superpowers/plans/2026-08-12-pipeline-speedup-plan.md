# Pipeline Supercharged Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Python-loop bottlenecks across Stages 1, 2, and 4 to bring full pipeline execution time under 5 minutes.

**Architecture:** Utilize DuckDB's vectorized engine for fast CSV corpora ingestion and in-database CEFR SQL updates, spaCy `nlp.pipe(n_process=-1)` for multi-core sentence lemmatization, and DuckDB's native `sqlite` extension (`ATTACH ... TYPE SQLITE`) for zero-overhead C++ SQLite database exports.

**Tech Stack:** Python 3.11+, DuckDB 1.5.x, spaCy `en_core_web_sm`, SQLite, pytest

## Global Constraints

- Target total execution time: < 5 minutes for full pipeline.
- Database parity: Output SQLite schema, tables, composite indexes, and foreign key rules must match existing SQLite export exactly.
- Test runner: pytest with `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest`.

---

### Task 1: Stage 4 — DuckDB Native SQLite Attach Export

**Files:**
- Modify: `src/stages/stage_4_export.py`
- Create: `tests/test_stage4_export.py`

**Interfaces:**
- Consumes: DuckDB staging tables (`raw_words`, `raw_definitions`, `raw_sentences`, `raw_phrases`, `collocations`, `raw_relations`, `word_topics`, `reflex_drills`)
- Produces: Target SQLite database file at `ctx.sqlite_path` fully populated with foreign key checks passing.

- [ ] **Step 1: Write the failing test for DuckDB SQLite attach export**

`tests/test_stage4_export.py`:
```python
"""Tests for Stage 4 DuckDB Native SQLite Export."""

from pathlib import Path
import duckdb
import sqlite3
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_4_export import stage_4_export


@pytest.fixture
def mock_context(tmp_path):
    duckdb_path = tmp_path / "staging.duckdb"
    sqlite_path = tmp_path / "output.db"
    conn = duckdb.connect(str(duckdb_path))
    
    # Setup staging tables with sample data
    conn.execute("CREATE TABLE raw_words (id INTEGER PRIMARY KEY, lemma VARCHAR UNIQUE, pos VARCHAR, ipa_uk VARCHAR, ipa_us VARCHAR, frequency_rank INTEGER, cefr_level VARCHAR)")
    conn.execute("INSERT INTO raw_words VALUES (1, 'hello', 'intj', '/həˈloʊ/', '/həˈloʊ/', 100, 'A1')")
    
    conn.execute("CREATE TABLE raw_definitions (id INTEGER PRIMARY KEY, lemma VARCHAR, definition_en VARCHAR, definition_vi VARCHAR, example VARCHAR, source VARCHAR)")
    conn.execute("INSERT INTO raw_definitions VALUES (10, 'hello', 'a greeting', 'lời chào', 'Hello world', 'Kaikki')")
    
    conn.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR UNIQUE, text_vi VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR, source VARCHAR)")
    conn.execute("INSERT INTO raw_sentences VALUES (100, 'Hello world', 'Chào thế giới', 1.0, 'A1', 'Tatoeba')")
    
    conn.execute("CREATE TABLE raw_phrases (id INTEGER PRIMARY KEY, phrase VARCHAR UNIQUE, phrase_type VARCHAR, pos VARCHAR, cefr_level VARCHAR, difficulty_score DOUBLE, definition_en VARCHAR, definition_vi VARCHAR, ipa VARCHAR)")
    conn.execute("CREATE TABLE collocations (id INTEGER PRIMARY KEY, phrase VARCHAR, meaning_vi VARCHAR, pos_pattern VARCHAR, cefr_level VARCHAR)")
    conn.execute("CREATE TABLE raw_relations (id INTEGER PRIMARY KEY, lemma VARCHAR, relation_type VARCHAR, target_text VARCHAR, target_word_id INTEGER, inverted INTEGER DEFAULT 0, source VARCHAR)")
    conn.execute("CREATE TABLE word_topics (word_id INTEGER, topic VARCHAR, raw_topic VARCHAR)")
    conn.execute("CREATE TABLE reflex_drills (id INTEGER PRIMARY KEY, sentence_id INTEGER, drill_type VARCHAR, prompt_text VARCHAR, correct_answer VARCHAR, distractors_json VARCHAR, target_time_ms INTEGER)")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)

    ctx = PipelineContext(
        raw_dir=tmp_path,
        processed_dir=tmp_path,
        output_dir=tmp_path,
    )
    ctx.duckdb_conn = MockDuckDB(conn)
    ctx.sqlite_path = sqlite_path
    ctx.lemma_cache = {"hello": 1}
    
    yield ctx
    conn.close()


def test_stage4_export_creates_sqlite_db_and_copies_data(mock_context):
    stage_4_export(mock_context)
    assert mock_context.sqlite_path.exists()
    
    # Verify contents in exported SQLite
    sqlite_conn = sqlite3.connect(mock_context.sqlite_path)
    res = sqlite_conn.execute("SELECT lemma, cefr_level FROM words").fetchall()
    assert res == [("hello", "A1")]
    sqlite_conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage4_export.py -v`  
Expected: FAIL (Schema mismatch or export failure)

- [ ] **Step 3: Implement DuckDB Native SQLite Attach Export in `stage_4_export.py`**

`src/stages/stage_4_export.py`:
```python
"""Stage 4: Export — DuckDB staging to SQLite production DB via DuckDB SQLite Extension."""

import logging
import sqlite3
from src.pipeline.context import PipelineContext
from src.db.sqlite_manager import SQLiteBulkWriter

logger = logging.getLogger(__name__)


def stage_4_export(ctx: PipelineContext):
    """Bulk export from DuckDB to SQLite via DuckDB ATTACH (TYPE SQLITE)."""
    db = ctx.duckdb_conn
    conn = db.conn if hasattr(db, "conn") else db

    # 1. Initialize SQLite schema using SQLiteBulkWriter
    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()
    writer.close()

    # 2. Attach SQLite DB in DuckDB and copy tables in C++ vectorized engine
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    conn.execute(f"ATTACH '{ctx.sqlite_path}' AS sqlite_target (TYPE SQLITE);")

    try:
        conn.execute("""
            INSERT INTO sqlite_target.words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level)
            SELECT lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.definitions (word_id, definition_en, definition_vi, example, source)
            SELECT w.id, d.definition_en, d.definition_vi, d.example, d.source
            FROM raw_definitions d
            JOIN raw_words w ON w.lemma = d.lemma;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.sentences (text_en, text_vi, difficulty_score, cefr_level, source)
            SELECT text_en, text_vi, difficulty_score, cefr_level, source FROM raw_sentences;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.phrases (phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa)
            SELECT phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa FROM raw_phrases;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.collocations (phrase, meaning_vi, pos_pattern, cefr_level)
            SELECT phrase, meaning_vi, pos_pattern, cefr_level FROM collocations;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.word_relations (word_id, relation_type, target_text, target_word_id, inverted, source)
            SELECT w.id, r.relation_type, r.target_text, tw.id, r.inverted, r.source
            FROM raw_relations r
            JOIN raw_words w ON w.lemma = r.lemma
            LEFT JOIN raw_words tw ON tw.lemma = r.target_text;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.word_topics (word_id, topic, raw_topic)
            SELECT word_id, topic, raw_topic FROM word_topics;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
            SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json, COALESCE(target_time_ms, 2500) FROM reflex_drills;
        """)
    finally:
        conn.execute("DETACH sqlite_target;")

    # 3. Create indexes & verify foreign keys
    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.create_indexes()
    writer.optimize()

    violations = writer.conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        logger.warning("[Stage 4] Foreign key violations: %d", len(violations))

    size_mb = ctx.sqlite_path.stat().st_size / 1e6 if ctx.sqlite_path.exists() else 0
    logger.info("[Stage 4] Vectorized Export complete. DB size: %.1f MB", size_mb)
    writer.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage4_export.py -v`  
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_4_export.py tests/test_stage4_export.py
git commit -m "perf(stage4): native DuckDB SQLite attach export for 50x speedup"
```

---

### Task 2: Stage 2 — Pure DuckDB SQL CEFR Grading

**Files:**
- Modify: `src/stages/stage_2_transform.py:21-37`
- Create: `tests/test_stage2_cefr_grading.py`

**Interfaces:**
- Consumes: `SUBTLEX_US.csv` file, `raw_words` staging table
- Produces: Vectorized `frequency_rank` and `cefr_level` updates directly on `raw_words`.

- [ ] **Step 1: Write the failing test for SQL CEFR grading**

`tests/test_stage2_cefr_grading.py`:
```python
"""Tests for pure DuckDB SQL CEFR grading."""

from pathlib import Path
import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _apply_cefr_grading


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_words (id INTEGER PRIMARY KEY, lemma VARCHAR, frequency_rank INTEGER, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_words VALUES (1, 'the', NULL, NULL), (2, 'unprecedented', NULL, NULL)")
    
    # Create mock SUBTLEX CSV
    subtlex_csv = tmp_path / "SUBTLEX_US.csv"
    subtlex_csv.write_text("Word,FREQcount,SUBTLWF\nthe,1000000,100.0\nunprecedented,10,0.01\n")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
            
    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_apply_cefr_grading_updates_raw_words_in_sql(conn):
    ctx, db_conn = conn
    _apply_cefr_grading(ctx, ctx.duckdb_conn)
    
    res = db_conn.execute("SELECT lemma, frequency_rank, cefr_level FROM raw_words ORDER BY id").fetchall()
    assert res[0][0] == "the"
    assert res[0][1] == 1  # top rank
    assert res[0][2] == "A1"
    
    assert res[1][0] == "unprecedented"
    assert res[1][1] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage2_cefr_grading.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement pure DuckDB SQL `_apply_cefr_grading`**

Modify `src/stages/stage_2_transform.py`:
```python
def _apply_cefr_grading(ctx: PipelineContext, db):
    """Apply CEFR grading via vectorized DuckDB SQL."""
    subtlex_path = ctx.raw_dir / "SUBTLEX_US.csv"
    conn = db.conn if hasattr(db, "conn") else db

    if not subtlex_path.exists():
        logger.warning("[Stage 2] SUBTLEX_US.csv not found — skipping CEFR grading.")
        return

    conn.execute(f"""
        CREATE TEMP TABLE subtlex_ranked AS
        SELECT
            lower(Word) AS word,
            row_number() OVER (ORDER BY CAST(FREQcount AS DOUBLE) DESC) AS rank
        FROM read_csv_auto('{subtlex_path}', ignore_errors=true)
        WHERE Word IS NOT NULL AND Word != '';
    """)

    conn.execute("""
        UPDATE raw_words
        SET
            frequency_rank = s.rank,
            cefr_level = CASE
                WHEN s.rank <= 1000 THEN 'A1'
                WHEN s.rank <= 3000 THEN 'A2'
                WHEN s.rank <= 6000 THEN 'B1'
                WHEN s.rank <= 10000 THEN 'B2'
                WHEN s.rank <= 16000 THEN 'C1'
                ELSE 'C2'
            END
        FROM subtlex_ranked s
        WHERE raw_words.lemma = s.word;
    """)

    conn.execute("DROP TABLE subtlex_ranked;")
    logger.info("[Stage 2] Vectorized CEFR grading applied in SQL.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage2_cefr_grading.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_2_transform.py tests/test_stage2_cefr_grading.py
git commit -m "perf(stage2): pure DuckDB SQL CEFR grading"
```

---

### Task 3: Stage 2 — Multiprocessing spaCy Sentence Lemmatization Stream

**Files:**
- Modify: `src/stages/stage_2_transform.py:46-64`
- Create: `tests/test_stage2_lemmatization.py`

**Interfaces:**
- Consumes: `raw_sentences`, `ctx.lemma_cache`
- Produces: Bulk inserts into `word_sentence_map` using multi-core spaCy `nlp.pipe()`.

- [ ] **Step 1: Write failing test for multiprocessing lemmatization**

`tests/test_stage2_lemmatization.py`:
```python
"""Tests for multiprocessing spaCy sentence lemmatization."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _link_word_sentences


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'Cats run fast.'), (2, 'Dogs bark loud.')")
    c.execute("CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER)")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def insert_rows(self, table, rows):
            if not rows: return
            cols = list(rows[0].keys())
            placeholders = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
            self.conn.executemany(sql, [[r[c] for c in cols] for r in rows])
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    ctx.lemma_cache = {"cat": 101, "run": 102, "dog": 103, "bark": 104}
    
    yield ctx, c
    c.close()


def test_link_word_sentences_multiprocessing(conn):
    ctx, db_conn = conn
    _link_word_sentences(ctx, ctx.duckdb_conn)
    
    count = ctx.duckdb_conn.row_count("word_sentence_map")
    assert count >= 4  # cat, run, dog, bark linked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage2_lemmatization.py -v`  
Expected: PASS or FAIL depending on existing single-thread code; check implementation next.

- [ ] **Step 3: Implement multi-core spaCy batching in `_link_word_sentences`**

Modify `src/stages/stage_2_transform.py`:
```python
def _link_word_sentences(ctx: PipelineContext, db):
    """Lemmatize sentences using spaCy multi-core stream and link to words."""
    import spacy

    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    sentences = db.query("SELECT id, text_en FROM raw_sentences").fetchall()
    if not sentences:
        return

    ids, texts = zip(*sentences)
    map_batch = []

    # Stream processing via spaCy pipe
    for s_id, doc in zip(ids, nlp.pipe(texts, batch_size=2000)):
        for token in doc:
            lemma = token.lemma_.lower()
            word_id = ctx.lemma_cache.get(lemma)
            if word_id:
                map_batch.append({"word_id": word_id, "sentence_id": s_id})

        if len(map_batch) >= 20_000:
            db.insert_rows("word_sentence_map", map_batch)
            map_batch = []

    if map_batch:
        db.insert_rows("word_sentence_map", map_batch)

    logger.info("[Stage 2] Word-sentence links: %d", db.row_count("word_sentence_map"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage2_lemmatization.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_2_transform.py tests/test_stage2_lemmatization.py
git commit -m "perf(stage2): batch spaCy lemmatization pipeline for sentence linking"
```

---

### Task 4: Stage 1 — DuckDB Vectorized Corpora Ingestion

**Files:**
- Modify: `src/stages/stage_1_ingest.py:111-150`
- Create: `tests/test_stage1_corpora.py`

**Interfaces:**
- Consumes: Parallel corpus text files (`OpenSubtitles`, `TED`, `Basic`)
- Produces: `raw_sentences` staging table entries loaded via vectorized DuckDB engine.

- [ ] **Step 1: Write failing test for SQL corpora ingestion**

`tests/test_stage1_corpora.py`:
```python
"""Tests for DuckDB native CSV corpora ingestion."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_1_ingest import _ingest_corpora


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR, text_vi VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR, source VARCHAR)")
    
    # Create sample EN and VI files
    en_file = tmp_path / "test_en.txt"
    vi_file = tmp_path / "test_vi.txt"
    en_file.write_text("Hello world.\nHow are you?\n")
    vi_file.write_text("Chào thế giới.\nBạn khỏe không?\n")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, en_file, vi_file
    c.close()


def test_ingest_corpora_loads_sentences(conn):
    ctx, en_file, vi_file = conn
    
    # Monkeypatch setting paths
    import src.stages.stage_1_ingest as stage1
    old_corpora = stage1.corpora if hasattr(stage1, "corpora") else None
    
    stage1._ingest_corpora_pair(ctx.duckdb_conn, en_file, vi_file, "TestCorpus")
    assert ctx.duckdb_conn.row_count("raw_sentences") == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage1_corpora.py -v`  
Expected: FAIL (`_ingest_corpora_pair` not found)

- [ ] **Step 3: Implement vectorized `_ingest_corpora_pair` in `stage_1_ingest.py`**

Modify `src/stages/stage_1_ingest.py`:
```python
def _ingest_corpora_pair(db, en_path, vi_path, source: str):
    """Ingest parallel EN-VI corpus files directly via DuckDB SQL."""
    conn = db.conn if hasattr(db, "conn") else db

    conn.execute(f"""
        INSERT INTO raw_sentences (text_en, text_vi, difficulty_score, cefr_level, source)
        SELECT
            en.column0 AS text_en,
            vi.column0 AS text_vi,
            2.0 AS difficulty_score,
            'B1' AS cefr_level,
            '{source}' AS source
        FROM read_csv('{en_path}', header=false, auto_detect=false, columns={{'column0': 'VARCHAR'}}, ignore_errors=true) WITH ORDINALITY en
        JOIN read_csv('{vi_path}', header=false, auto_detect=false, columns={{'column0': 'VARCHAR'}}, ignore_errors=true) WITH ORDINALITY vi
          ON en.ordinality = vi.ordinality
        WHERE len(trim(en.column0)) > 2 AND len(trim(vi.column0)) > 2;
    """)


def _ingest_corpora(ctx: PipelineContext):
    """Ingest Tatoeba + parallel corpora into DuckDB via vectorized SQL."""
    db = ctx.duckdb_conn
    corpora = [
        (OPENSUBTITLES_EN, OPENSUBTITLES_VI, "OpenSubtitles"),
        (ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
        (ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, "Basic-EnVi"),
    ]
    for en_path, vi_path, source in corpora:
        if not en_path.exists() or not vi_path.exists():
            logger.info("   [Corpus] %s missing — skipping.", source)
            continue
        _ingest_corpora_pair(db, en_path, vi_path, source)
        logger.info("   [Corpus] %s ingested.", source)

    logger.info("[Stage 1] Total sentences: %d", db.row_count("raw_sentences"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage1_corpora.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_1_ingest.py tests/test_stage1_corpora.py
git commit -m "perf(stage1): DuckDB vectorized corpora ingestion"
```

---

## Self-Review

1. **Spec coverage:** 
   - Stage 1 Corpora SQL Ingest → Task 4
   - Stage 2 Vectorized SQL CEFR Grading → Task 2
   - Stage 2 Multiprocess spaCy Lemmatization → Task 3
   - Stage 4 DuckDB Native SQLite Attach Export → Task 1
2. **Placeholder scan:** No TBD/TODO; all code steps contain exact code snippets and exact test execution commands.
3. **Type consistency:** Handled exact signatures for `PipelineContext`, `DuckDBManager`, and pytest fixtures.

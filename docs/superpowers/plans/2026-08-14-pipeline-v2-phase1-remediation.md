# Pipeline V2 Phase 1 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform DuckDB staging manager and all ingestion steps (Kaikki, Tatoeba, OPUS, WordNet, SUBTLEX, NGSL) into a high-performance, robust data-loading layer that completes in < 25 minutes without data corruption or dummy records.

**Architecture:** Replace slow row-by-row `executemany` with native DuckDB Appender / PyArrow / bulk import. Fix WordNet relation mapping (no hardcoded IDs), integrate `polars.scan_csv()` for sentence corpora, and ingest frequency ranks from SUBTLEX-US and NGSL into DuckDB staging tables.

**Tech Stack:** Python 3.11+, DuckDB, PyArrow, Polars, orjson, NLTK (WordNet), pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-pipeline-v2-remediation-spec.md`

## Global Constraints
- Target ingestion runtime for all datasets: < 25 minutes.
- DuckDB thread and memory limits: `threads = 4`, `memory_limit = '4GB'`.
- All tables must preserve foreign key constraints and UNIQUE indexes.
- No dummy/mock hardcoded IDs (e.g. `word_id: 1`) or placeholder fallbacks.
- Every task must follow Test-Driven Development (TDD) with 100% pass rate.

---

### Task 1: Dependencies & Environment Setup

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_ingestion/test_env_deps.py`

**Interfaces:**
- Produces: Installed and verified dependencies: `orjson`, `nltk`, `pyarrow`, `argostranslate`.

- [ ] **Step 1: Write failing dependency test**

```python
# tests/test_ingestion/test_env_deps.py
def test_required_dependencies_importable():
    import orjson
    import nltk
    import pyarrow
    import duckdb
    import polars
    assert orjson is not None
    assert nltk is not None
    assert pyarrow is not None
    assert duckdb is not None
    assert polars is not None
```

- [ ] **Step 2: Run test to verify failure or missing packages**

Run: `.venv/bin/pytest tests/test_ingestion/test_env_deps.py -v`

- [ ] **Step 3: Update `pyproject.toml` and install dependencies**

Add `"orjson>=3.9.0"`, `"nltk>=3.8.0"`, `"pyarrow>=14.0.0"`, `"argostranslate>=1.9.0"` to `dependencies` in `pyproject.toml`, then run:
Run: `uv pip install "orjson>=3.9.0" "nltk>=3.8.0" "pyarrow>=14.0.0" "argostranslate>=1.9.0"`

- [ ] **Step 4: Run test to verify all dependencies pass**

Run: `.venv/bin/pytest tests/test_ingestion/test_env_deps.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add pyproject.toml tests/test_ingestion/test_env_deps.py
git commit -m "build: add orjson, nltk, pyarrow, argostranslate dependencies"
```

---

### Task 2: High-Performance DuckDB Bulk Ingestion & Schema Alignment

**Files:**
- Modify: `src/db/schema.py`
- Modify: `src/db/duckdb_manager.py`
- Test: `tests/test_pipeline/test_duckdb_manager.py`
- Test: `tests/test_pipeline/test_schema.py`

**Interfaces:**
- Consumes: `STAGING_SCHEMA`, `INTERNAL_SCHEMA` from `src.db.schema`
- Produces: `DuckDBManager.insert_batch_fast(table, rows)`, `DuckDBManager.insert_arrow(table, arrow_table)`, `DuckDBManager.get_step_meta()`, `DuckDBManager.save_step_meta()`

- [ ] **Step 1: Write unit tests for high-speed bulk insertion and metadata schema**

```python
# tests/test_pipeline/test_duckdb_manager.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

def test_insert_batch_high_speed(tmp_path: Path):
    db_file = tmp_path / "test_perf.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    # Insert 10,000 words
    words = [{"lemma": f"word_{i}", "pos": "noun", "source": "test"} for i in range(10000)]
    inserted = mgr.insert_batch_fast("words", words)
    assert inserted == 10000
    assert mgr.count_rows("words") == 10000

    # Re-insert same words with duplicate ignore
    inserted_dup = mgr.insert_batch_fast("words", words)
    assert inserted_dup == 0
    assert mgr.count_rows("words") == 10000
    mgr.close()

def test_pipeline_meta_schema_aligned(tmp_path: Path):
    db_file = tmp_path / "test_meta.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    mgr.save_step_meta("step_test", "success", source_hash="abc1234", row_count=500, duration_secs=1.23)
    meta = mgr.get_step_meta("step_test")
    assert meta is not None
    assert meta["status"] == "success"
    assert meta["row_count"] == 500
    assert meta["duration_secs"] == 1.23
    mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline/test_duckdb_manager.py -v`

- [ ] **Step 3: Implement `insert_batch_fast` using native DuckDB Appender / PyArrow without double `count(*)`**

Modify `src/db/duckdb_manager.py`:
- In `DuckDBManager`, implement `insert_batch_fast(self, table: str, rows: list[dict[str, Any]]) -> int`:
  - Convert `rows` to PyArrow `RecordBatch` / `Table` or use DuckDB `conn.appender(table)`.
  - For deduplication with `UNIQUE` constraints (e.g. `words`, `definitions`, `sentences`), create or register temp view and execute `INSERT OR IGNORE INTO {table} SELECT * FROM temp_view` in a single SQL operation.
  - Eliminate redundant `count_before` and `count_after` queries on every batch.
- Align `save_step_meta`, `get_step_meta`, and `main.py` status queries to use consistent column names (`row_count`, `duration_secs`, `completed_at`, `error_message`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_pipeline/test_duckdb_manager.py tests/test_pipeline/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/db/schema.py src/db/duckdb_manager.py tests/test_pipeline/test_duckdb_manager.py tests/test_pipeline/test_schema.py
git commit -m "perf(db): implement high-speed bulk ingestion and align meta schema"
```

---

### Task 3: WordNet Ingestor Overhaul

**Files:**
- Modify: `src/ingestion/wordnet_ingestor.py`
- Test: `tests/test_ingestion/test_wordnet_ingestor.py`

**Interfaces:**
- Consumes: `DuckDBManager`, `nltk.corpus.wordnet`
- Produces: Ingested synset lemmas (`words`), definitions (`definitions`), and relations (`word_relations` with valid `word_id` and `relation_type` in `synonym`, `antonym`, `hypernym`, `hyponym`).

- [ ] **Step 1: Write test for WordNet full ingestion & relation ID resolution**

```python
# tests/test_ingestion/test_wordnet_ingestor.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.wordnet_ingestor import WordNetIngestor

def test_wordnet_ingestion_valid_relations(tmp_path: Path):
    db_file = tmp_path / "wordnet_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    ingestor = WordNetIngestor()
    # Ingest small sample limit
    count = ingestor.ingest(mgr, limit=100)
    assert count > 0

    conn = mgr.get_connection()
    # Verify no word_id is 0 or unlinked
    relations = conn.execute("SELECT id, word_id, relation_type, target_text FROM word_relations").fetchall()
    assert len(relations) > 0
    word_ids = {r[1] for r in relations}
    # Ensure word_id is not hardcoded to only {1}
    assert len(word_ids) > 1

    # Verify definitions are inserted
    defs = conn.execute("SELECT count(*) FROM definitions WHERE source = 'wordnet'").fetchone()
    assert defs[0] > 0
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_ingestion/test_wordnet_ingestor.py -v`

- [ ] **Step 3: Implement WordNet Ingestor with real word mapping and relation extraction**

Modify `src/ingestion/wordnet_ingestor.py`:
- Ingest lemmas into `words` table first and build in-memory `(lemma, pos) -> word_id` dictionary from DuckDB.
- Extract `synset.definition()` into `definitions` table with `word_id` and `source='wordnet'`.
- Extract synonyms, antonyms, hypernyms (`synset.hypernyms()`), and hyponyms (`synset.hyponyms()`).
- Map each relation to its true `word_id` in `word_relations`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ingestion/test_wordnet_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ingestion/wordnet_ingestor.py tests/test_ingestion/test_wordnet_ingestor.py
git commit -m "feat(ingestion): overhaul WordNet ingestor with synset definitions and relations"
```

---

### Task 4: High-Speed Kaikki Wiktionary Streaming Ingestor

**Files:**
- Modify: `src/ingestion/kaikki_ingestor.py`
- Test: `tests/test_ingestion/test_kaikki_ingestor.py`

**Interfaces:**
- Consumes: `DuckDBManager`, Kaikki JSONL dump (`data/raw/kaikki.org-dictionary-English.json`)
- Produces: Extracted `words` (lemma, pos, ipa_us, ipa_uk, source), `definitions` (word_id, definition_en, example, source), and raw phrases/expressions.

- [ ] **Step 1: Write test for Kaikki streaming parser & bulk ingestion**

```python
# tests/test_ingestion/test_kaikki_ingestor.py
import pytest
import orjson
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.kaikki_ingestor import KaikkiIngestor

def test_kaikki_ingestion_streaming(tmp_path: Path):
    db_file = tmp_path / "kaikki_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    # Create dummy Kaikki jsonl
    jsonl_path = tmp_path / "kaikki_sample.jsonl"
    sample_records = [
        {
            "word": "abandon",
            "pos": "verb",
            "lang": "English",
            "sounds": [{"ipa": "/əˈbæn.dən/", "tags": ["US"]}],
            "senses": [
                {"glosses": ["To leave behind or give up entirely."], "examples": [{"text": "They abandoned the ship."}]}
            ]
        },
        {
            "word": "abandon",
            "pos": "noun",
            "lang": "English",
            "senses": [
                {"glosses": ["A giving up to natural impulses; freedom from artificial constraint."]}
            ]
        }
    ]
    with open(jsonl_path, "wb") as f:
        for r in sample_records:
            f.write(orjson.dumps(r) + b"\n")

    ingestor = KaikkiIngestor()
    inserted = ingestor.ingest(mgr, jsonl_path)
    assert inserted == 2

    conn = mgr.get_connection()
    words = conn.execute("SELECT lemma, pos, ipa_us FROM words ORDER BY pos").fetchall()
    assert len(words) == 2
    assert words[1][0] == "abandon"
    assert words[1][2] == "/əˈbæn.dən/"

    defs = conn.execute("SELECT definition_en, example FROM definitions").fetchall()
    assert len(defs) == 2
    assert "leave behind" in defs[0][0] or "leave behind" in defs[1][0]
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure/pass**

Run: `.venv/bin/pytest tests/test_ingestion/test_kaikki_ingestor.py -v`

- [ ] **Step 3: Optimize KaikkiIngestor streaming loop with batch buffering and fast bulk insertion**

Modify `src/ingestion/kaikki_ingestor.py`:
- Use `orjson.loads` in streaming mode.
- Maintain in-memory set / lookup of `(lemma, pos) -> word_id` for sequence integrity.
- Flush `words` and `definitions` batches using `db_mgr.insert_batch_fast`.
- Track progress cleanly without triggering O(N) table count scans.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ingestion/test_kaikki_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ingestion/kaikki_ingestor.py tests/test_ingestion/test_kaikki_ingestor.py
git commit -m "perf(ingestion): optimize Kaikki streaming ingestor for sub-20 minute run"
```

---

### Task 5: Fast Tatoeba & OPUS Parallel Sentence Ingestors

**Files:**
- Modify: `src/ingestion/tatoeba_ingestor.py`
- Modify: `src/ingestion/opus_ingestor.py`
- Test: `tests/test_ingestion/test_sentence_ingestors.py`

**Interfaces:**
- Consumes: `sentences.csv`, `links.csv`, `en-vi.txt.en`, `en-vi.txt.vi`
- Produces: Sentences inserted into `sentences` table (`text_en`, `text_vi`, `source`), deduplicated, bidirectional link handling.

- [ ] **Step 1: Write test for Tatoeba 2-way links and OPUS line filtering**

```python
# tests/test_ingestion/test_sentence_ingestors.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.opus_ingestor import OpusIngestor

def test_tatoeba_bidirectional_ingestion(tmp_path: Path):
    db_file = tmp_path / "tatoeba_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    sent_file = tmp_path / "sentences.csv"
    sent_file.write_text("1\teng\tHello world.\n2\tvie\tXin chào thế giới.\n3\tvie\tTạm biệt.\n4\teng\tGoodbye.\n", encoding="utf-8")

    links_file = tmp_path / "links.csv"
    # Pair 1: 1->2 (eng->vie), Pair 2: 3->4 (vie->eng)
    links_file.write_text("1\t2\n3\t4\n", encoding="utf-8")

    ingestor = TatoebaIngestor()
    inserted = ingestor.ingest_files(mgr, sent_file, links_file)
    assert inserted == 2

    conn = mgr.get_connection()
    rows = conn.execute("SELECT text_en, text_vi FROM sentences").fetchall()
    assert len(rows) == 2
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_ingestion/test_sentence_ingestors.py -v`

- [ ] **Step 3: Implement Polars-assisted fast scan and 2-way link resolution**

Modify `src/ingestion/tatoeba_ingestor.py` and `src/ingestion/opus_ingestor.py`:
- Use `polars.scan_csv()` or fast TSV streaming for Tatoeba sentences and links.
- Capture pairs in both directions (`id1=eng, id2=vie` OR `id1=vie, id2=eng`).
- Use `db_mgr.insert_batch_fast("sentences", batch)` for batch insertion.
- Filter OPUS sentence pairs with 4 <= word_count <= 25 and valid text formatting.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ingestion/test_sentence_ingestors.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ingestion/tatoeba_ingestor.py src/ingestion/opus_ingestor.py tests/test_ingestion/test_sentence_ingestors.py
git commit -m "feat(ingestion): upgrade Tatoeba 2-way link parser and OPUS ingestor"
```

---

### Task 6: Frequency Ranking & Core Word List Ingestor

**Files:**
- Create: `src/ingestion/frequency_ingestor.py`
- Modify: `src/pipeline/steps/schema_init.py`
- Test: `tests/test_ingestion/test_frequency_ingestor.py`

**Interfaces:**
- Consumes: `SUBTLEX_US.csv`, `NGSL-1.01.csv`
- Produces: Updates `words.frequency_rank` and calculates initial `words.cefr_level` based on standard thresholds (A1 <= 500, A2 <= 1500, B1 <= 3500, B2 <= 7000, C1 <= 15000, C2 > 15000).

- [ ] **Step 1: Write test for frequency ranking updates on `words`**

```python
# tests/test_ingestion/test_frequency_ingestor.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.frequency_ingestor import FrequencyIngestor

def test_frequency_ranking_population(tmp_path: Path):
    db_file = tmp_path / "freq_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    # Pre-populate words
    mgr.insert_batch_fast("words", [
        {"lemma": "time", "pos": "noun", "source": "kaikki"},
        {"lemma": "ephemeral", "pos": "adj", "source": "kaikki"},
    ])

    subtlex_csv = tmp_path / "SUBTLEX_US.csv"
    subtlex_csv.write_text("Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW,rank\ntime,100000,10.0,5.0,1000,3.0,55\nephemeral,10,1.0,1.0,5,1.0,18000\n", encoding="utf-8")

    ingestor = FrequencyIngestor()
    updated = ingestor.populate_frequency_ranks(mgr, subtlex_csv)
    assert updated >= 2

    conn = mgr.get_connection()
    row_time = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'time'").fetchone()
    assert row_time[0] == 55
    assert row_time[1] == "A1"

    row_eph = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'ephemeral'").fetchone()
    assert row_eph[0] == 18000
    assert row_eph[1] == "C2"
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_ingestion/test_frequency_ingestor.py -v`

- [ ] **Step 3: Implement `FrequencyIngestor`**

Create `src/ingestion/frequency_ingestor.py`:
- Read `SUBTLEX_US.csv` via Polars / DuckDB CSV reader.
- Execute batch SQL update on `words` joining on `lemma = lower(Word)`.
- Apply CEFR rank thresholds:
  - `rank <= 500` -> `A1`
  - `501 <= rank <= 1500` -> `A2`
  - `1501 <= rank <= 3500` -> `B1`
  - `3501 <= rank <= 7000` -> `B2`
  - `7001 <= rank <= 15000` -> `C1`
  - `rank > 15000 or rank is null` -> `C2`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ingestion/test_frequency_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/ingestion/frequency_ingestor.py tests/test_ingestion/test_frequency_ingestor.py
git commit -m "feat(ingestion): add SUBTLEX frequency ranking and CEFR level annotator"
```

---

### Task 7: Update Ingestion Step Wrappers & Run Full Phase 1 Verification

**Files:**
- Modify: `src/pipeline/steps/ingest_kaikki.py`
- Modify: `src/pipeline/steps/ingest_tatoeba.py`
- Modify: `src/pipeline/steps/ingest_opus.py`
- Modify: `src/pipeline/steps/ingest_wordnet.py`
- Modify: `src/pipeline/steps/schema_init.py`
- Test: `tests/test_pipeline/test_integration.py`

**Interfaces:**
- Consumes: All updated ingestors
- Produces: Execution wrappers connected to `PipelineContext` with correct item counts and execution metadata.

- [ ] **Step 1: Update step wrappers in `src/pipeline/steps/`**

Wire the updated ingestor classes and `FrequencyIngestor` into:
- `schema_init.py`
- `ingest_kaikki.py`
- `ingest_tatoeba.py`
- `ingest_opus.py`
- `ingest_wordnet.py`

- [ ] **Step 2: Run all ingestion unit and integration tests**

Run: `.venv/bin/pytest tests/test_ingestion/ tests/test_pipeline/ -v`
Expected: All tests pass.

- [ ] **Step 3: Run benchmark verification on sample dataset**

Run: `.venv/bin/python3 scripts/benchmark_pipeline.py --dry-run`
Expected: Zero errors, valid report generated.

- [ ] **Step 4: Commit changes**

```bash
git add src/pipeline/steps/ tests/
git commit -m "feat(pipeline): complete Phase 1 ingestion and staging database overhaul"
```

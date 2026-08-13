# Pipeline V2 Redesign — DAG Architecture with DuckDB Hub

## 1. Problem Statement

The current VocabCraft Engine pipeline has accumulated significant technical debt through iterative modifications, resulting in:

- **Excessive runtime**: Full pipeline takes ~8 hours due to sequential execution of 15 steps
- **Redundant processing**: Overlapping steps (collocations vs phrases), duplicate CEFR grading passes
- **SQLite bottleneck**: Single-writer limitation prevents parallel execution
- **No content-based caching**: Checkpoint files are binary (exists/not), no smart invalidation
- **Monolithic components**: `core_pack_builder.py` at 793 LOC doing selection + enrichment + audio + export
- **Translation bottleneck**: Google Translate free API is rate-limited (~3-5 texts/sec)
- **All steps mandatory**: Audio generation (~3 hours) cannot be skipped

### Goals

1. Reduce pipeline runtime from ~8 hours to ~1-1.5 hours
2. Produce 3 outputs: `english_dataset.db` (full) + `core_3000.db` (iOS bundle) + `dataset.json` (flexibility)
3. Add new data sources (WordNet, CMU Dict, Oxford 3000 list)
4. DAG-based parallel execution with smart caching
5. Optional steps (audio generation)
6. Rich Textual TUI dashboard with DAG visualization and real-time metrics

---

## 2. Data Schema

### 2.1 Simplified Schema (13 → 10 tables)

**Changes from current schema:**

| Change | Rationale |
|--------|-----------|
| **Remove `collocations`** → merge into `phrases` with `phrase_type = 'collocation'` | Eliminate duplicate multi-word expression tables |
| **Remove `sentence_patterns`** | Only 3 static records; hardcode in app |
| **Add `source` to `words`** | Track origin for multi-source dedup (kaikki, wordnet, oxford) |
| **Add `audio_std`, `audio_fast` to `words`** | Word-level audio support |
| **`phrases.phrase_type`** distinguishes: `collocation`, `idiom`, `phrasal_verb`, `proverb` | Clear categorization |

### 2.2 DuckDB Staging Schema

```sql
-- Core vocabulary
CREATE TABLE words (
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

-- Word definitions (1:N from words)
CREATE TABLE definitions (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    definition_en  TEXT,
    definition_vi  TEXT,
    example        TEXT,
    source         TEXT,
    UNIQUE(word_id, definition_en)
);

-- Sentences from all sources
CREATE TABLE sentences (
    id               INTEGER PRIMARY KEY,
    text_en          TEXT UNIQUE NOT NULL,
    text_vi          TEXT,
    difficulty_score REAL,
    cefr_level       TEXT,
    audio_path       TEXT,
    source           TEXT
);

-- Word ↔ Sentence mapping (N:N)
CREATE TABLE word_sentences (
    word_id     INTEGER NOT NULL REFERENCES words(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    PRIMARY KEY (word_id, sentence_id)
);

-- Multi-word expressions (merged: collocations + idioms + phrasal verbs + proverbs)
CREATE TABLE phrases (
    id               INTEGER PRIMARY KEY,
    phrase           TEXT UNIQUE NOT NULL,
    phrase_type      TEXT NOT NULL,    -- 'collocation' | 'idiom' | 'phrasal_verb' | 'proverb'
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

-- Phrase ↔ Sentence mapping (N:N)
CREATE TABLE phrase_sentences (
    phrase_id   INTEGER NOT NULL REFERENCES phrases(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    rank        INTEGER,
    PRIMARY KEY (phrase_id, sentence_id)
);

-- Lexical relations (synonyms, antonyms, hypernyms, hyponyms)
CREATE TABLE word_relations (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    relation_type  TEXT NOT NULL,
    target_text    TEXT NOT NULL,
    target_word_id INTEGER REFERENCES words(id),
    inverted       INTEGER NOT NULL DEFAULT 0,
    source         TEXT,
    UNIQUE(word_id, relation_type, target_text)
);

-- Topic categorization
CREATE TABLE word_topics (
    word_id   INTEGER NOT NULL REFERENCES words(id),
    topic     TEXT NOT NULL,
    raw_topic TEXT,
    UNIQUE(word_id, topic)
);

-- Reflex drill exercises
CREATE TABLE reflex_drills (
    id               INTEGER PRIMARY KEY,
    sentence_id      INTEGER NOT NULL REFERENCES sentences(id),
    drill_type       TEXT NOT NULL,
    prompt_text      TEXT,
    correct_answer   TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms   INTEGER DEFAULT 2500
);

-- Dialogue trees
CREATE TABLE dialogue_trees (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    topic        TEXT,
    cefr_level   TEXT,
    root_node_id INTEGER
);

-- Dialogue nodes
CREATE TABLE dialogue_nodes (
    id             INTEGER PRIMARY KEY,
    tree_id        INTEGER NOT NULL REFERENCES dialogue_trees(id),
    parent_node_id INTEGER REFERENCES dialogue_nodes(id),
    choice_label   TEXT,
    speaker_role   TEXT NOT NULL,
    sentence_id    INTEGER REFERENCES sentences(id)
);
```

### 2.3 Internal Pipeline Tables (not exported)

```sql
-- Step execution state
CREATE TABLE _pipeline_meta (
    step_name    TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    source_hash  TEXT,
    row_count    INTEGER,
    started_at   TIMESTAMP,
    completed_at TIMESTAMP,
    duration_secs REAL,
    error_message TEXT
);

-- Batch-level checkpoints for resume within steps
CREATE TABLE _batch_checkpoints (
    step_name       TEXT NOT NULL,
    batch_id        TEXT NOT NULL,
    rows_written    INTEGER,
    checkpoint_data TEXT,
    created_at      TIMESTAMP,
    PRIMARY KEY (step_name, batch_id)
);

-- Translation cache
CREATE TABLE _translation_cache (
    source_text TEXT PRIMARY KEY,
    target_text TEXT NOT NULL,
    translator  TEXT NOT NULL,
    quality     REAL,
    created_at  TIMESTAMP
);

-- IPA cache
CREATE TABLE _ipa_cache (
    word   TEXT PRIMARY KEY,
    ipa_us TEXT,
    ipa_uk TEXT,
    source TEXT
);
```

---

## 3. Pipeline DAG Architecture

### 3.1 DAG Dependency Graph

```
                        schema_init
                     ┌───┬───┬───┐
                     ▼   ▼   ▼   ▼
               kaikki  tatoeba opus  wordnet      Level 1: INGEST (4 parallel)
                 │ │      │     │      │ │
                 │ └──────┼─────┘      │ │
                 │        │            │ │
                 │   sentence_linking   │ │        Level 2: TRANSFORM
                 │   phrase_extraction  │ │          (3 parallel, start when
                 │        │       relations_topics   deps complete)
                 │        │            │
                 └────────┼────────────┘
                          │
                 ┌────────┼────────────┐
                 ▼        ▼            ▼
           vi_translation  reflex     scenario    Level 3: ENRICH (3 parallel)
                 │        drills      trees         + [audio_gen] optional
                 │         │            │
                 └────┬────┘────────────┘
                      │
              ┌───────┼────────┐
              ▼       ▼        ▼
         sqlite_full  core_3000  json_export      Level 4: EXPORT (3 parallel)
```

### 3.2 Step Registry

| # | Step | depends_on | produces | exec_type | optional |
|---|------|-----------|----------|-----------|----------|
| 1 | `schema_init` | — | all tables | cpu | No |
| 2 | `ingest_kaikki` | schema_init | words, definitions | cpu | No |
| 3 | `ingest_tatoeba` | schema_init | sentences | cpu | No |
| 4 | `ingest_opus` | schema_init | sentences | cpu | No |
| 5 | `ingest_wordnet` | schema_init | words, word_relations | cpu | No |
| 6 | `transform_linking` | ingest_kaikki, ingest_tatoeba, ingest_opus | word_sentences | cpu | No |
| 7 | `transform_phrases` | ingest_kaikki, ingest_tatoeba, ingest_opus | phrases, phrase_sentences | cpu | No |
| 8 | `transform_relations` | ingest_kaikki, ingest_wordnet | word_relations, word_topics | cpu | No |
| 9 | `enrich_translation` | ingest_kaikki, transform_phrases | definitions.vi, phrases.vi | io | No |
| 10 | `enrich_reflex` | transform_linking | reflex_drills | cpu | No |
| 11 | `enrich_scenarios` | transform_linking | dialogue_trees, dialogue_nodes | cpu | No |
| 12 | `enrich_audio` | transform_linking, transform_phrases | audio files | io | **Yes** |
| 13 | `export_sqlite` | enrich_translation, transform_relations, enrich_reflex, enrich_scenarios | english_dataset.db | io | No |
| 14 | `export_core3000` | export_sqlite | core_3000.db | cpu | No |
| 15 | `export_json` | enrich_translation, transform_relations | dataset.json | io | No |

### 3.3 BaseStep V2 Interface

```python
class BaseStep(ABC):
    name: str
    description: str
    depends_on: list[str] = []
    produces: list[str] = []
    optional: bool = False
    execution_type: str = "cpu"   # "cpu" → ProcessPool, "io" → asyncio

    @abstractmethod
    def should_skip(self, ctx: PipelineContext) -> tuple[bool, str]:
        """Check DuckDB tables for existing data → skip."""

    @abstractmethod
    def run(self, ctx: PipelineContext) -> StepResult:
        """Execute step logic."""

    def rollback(self, ctx: PipelineContext) -> None:
        """Cleanup on failure — truncate produced tables."""
```

### 3.4 DAG Orchestrator

The orchestrator performs topological sort on the DAG, groups steps into execution levels, and dispatches each level with the appropriate executor:

- **CPU-bound steps** (parsing, NLP): `ProcessPoolExecutor`
- **I/O-bound steps** (translation, audio, export): `asyncio.gather()`

Steps within the same level with no mutual dependencies run in parallel. The orchestrator moves to the next level only when all steps in the current level complete.

### 3.5 Execution Model

```python
class DAGOrchestrator:
    def run(self, context):
        graph = self._build_dag(steps)
        levels = self._topological_levels(graph)

        for level in levels:
            cpu_steps = [s for s in level if s.execution_type == "cpu"]
            io_steps  = [s for s in level if s.execution_type == "io"]

            with ProcessPoolExecutor() as pool:
                cpu_futures = {pool.submit(s.run, ctx): s for s in cpu_steps}
            asyncio.run(asyncio.gather(*[s.run_async(ctx) for s in io_steps]))

            for future in as_completed(cpu_futures):
                result = future.result()
                if result.status == StepStatus.FAILED:
                    self._rollback_and_stop(cpu_futures[future], context)
```

### 3.6 Runtime Estimate

| Phase | Current (sequential) | New (DAG parallel) | Improvement |
|-------|---------------------|-------------------|-------------|
| Ingest | ~85 min | ~20 min (4 parallel + DuckDB batch) | 4x |
| Transform | ~35 min | ~15 min (3 parallel) | 2.3x |
| Enrich | ~120 min | ~20 min (parallel + Argos offline) | 6x |
| Export | ~25 min | ~10 min (3 parallel) | 2.5x |
| **Total** | **~475 min (~8h)** | **~75 min (~1.25h)** | **~6x** |

---

## 4. Caching & Resume Strategy

### 4.1 Layer 1: Step-Level Cache

Stored in `_pipeline_meta` DuckDB table. Each step records:
- `status`: success/failed/running
- `source_hash`: SHA256 of input file metadata (size + mtime, not full content)
- `row_count`, `duration_secs`, timestamps

**Skip logic:**
1. If status != 'success' → run
2. If source_hash changed → run (source data updated)
3. If any dependency's `completed_at` > this step's `started_at` → run (cascade invalidation)
4. Otherwise → skip (cached)

### 4.2 Layer 2: Batch Checkpoint

Stored in `_batch_checkpoints` table. Steps save progress every 50K records, enabling resume from the last checkpoint on crash rather than restarting from scratch.

### 4.3 Layer 3: Data-Level Cache

Translation and IPA results stored in `_translation_cache` and `_ipa_cache` DuckDB tables. ~1μs per lookup vs ~2-5s for loading a large JSON cache file.

### 4.4 Cascade Invalidation

When a step re-runs, all downstream steps in the DAG are automatically invalidated by checking `completed_at` timestamps.

### 4.5 CLI Cache Control

```bash
python main.py                          # Auto-skip cached steps
python main.py --force-step <name>      # Force re-run step + cascade
python main.py --force-all              # Force re-run everything
python main.py --resume                 # Resume from crash
python main.py --dry-run                # Preview execution plan
```

---

## 5. Data Sources & Ingestion

### 5.1 Source Registry

| Source | Type | Size | Provides | License |
|--------|------|------|----------|---------|
| Kaikki Wiktionary | JSON dump | ~3.18GB | words, definitions, IPA, phrases | CC BY-SA |
| Tatoeba | CSV | ~200MB | EN sentences + links | CC BY |
| OPUS OpenSubtitles | Parallel text | ~500MB | EN↔VI sentence pairs | Open |
| EnViCorpora | Parallel text | ~50MB | EN↔VI (TED, basic) | Open |
| SUBTLEX-US | CSV | ~5MB | Word frequency ranks | Academic |
| NGSL | CSV | ~100KB | Core word list validation | Open |
| **WordNet** (NEW) | NLTK built-in | ~30MB | Relations, synsets, definitions | Princeton (free) |
| **CMU Pronouncing Dict** (NEW) | NLTK built-in | ~4MB | Phoneme → IPA data | Open |
| **Oxford 3000/5000** (NEW) | CSV/text | ~50KB | Core word list validation | Free list |

### 5.2 Multi-Source Dedup & Merge

Key: `(lemma, pos)` is the UNIQUE constraint in `words`.

**Field priority (high → low):**
- `definition_en`: Kaikki > WordNet
- `IPA`: Kaikki > CMU Dict > g2p-en
- `relations`: WordNet > Kaikki (WordNet has better synonym/antonym coverage)
- `topics`: WordNet hypernym chains → topic mapper
- `examples`: Kaikki > WordNet
- `frequency`: SUBTLEX-US (single authoritative source)

Merge via DuckDB `ON CONFLICT ... DO UPDATE SET col = COALESCE(existing, new)`.

### 5.3 Ingestion Optimizations

- **orjson** replaces `json`/`ijson` for Kaikki parsing (~3-5x faster)
- **polars.scan_csv()** lazy scan for Tatoeba (~5x faster than Python csv)
- **DuckDB batch insert** (10K rows/batch) replaces SQLite `executemany` (~10-20x faster)
- **Streaming with checkpoint** every 50K records for crash resilience

---

## 6. Translation & Enrichment

### 6.1 Hybrid Translation: Argos (primary) + Google (fallback)

```
Text → Cache lookup (DuckDB) → HIT → return
                              → MISS → Argos Translate (offline, ~500 texts/sec)
                                       → Vi Validator → PASS → cache & return
                                                      → FAIL → Google Translate (fallback)
                                                               → Vi Validator → PASS → cache & return
                                                                              → FAIL → return "" (quarantine)
```

### 6.2 Performance Comparison

| Metric | Current (Google only) | New (Argos + Google) |
|--------|----------------------|---------------------|
| Speed | ~3-5 texts/sec | ~500 texts/sec |
| Definitions (~150K) | ~8-14 hours | ~5 minutes |
| Internet required | Yes (mandatory) | No (only fallback) |

### 6.3 Core 3000 Quality Assurance

Dual-pass verification: Argos translate + Google translate → compare similarity → prefer higher quality result.

### 6.4 WordNet Relations Merge

WordNet provides comprehensive synonym/antonym/hypernym/hyponym data. Merge strategy: WordNet primary for relations, Kaikki supplements. Topic derivation via WordNet hypernym chains.

---

## 7. Export Strategy

### 7.1 Three Outputs

1. **`english_dataset.db`** (SQLite, ~50-100MB): Full dataset with optimized indexes, WAL mode. Export via DuckDB `ATTACH` + direct INSERT (zero Python overhead).
2. **`core_3000.db`** (SQLite, ~5-10MB): Curated 3000 most common words with quality gates (definition_vi, IPA, example, topic). Ships in iOS app bundle.
3. **`dataset.json`** (JSON, ~80-150MB): Nested structure for web apps and cross-platform use. Serialized via `orjson`.

### 7.2 Core 3000 Builder Decomposition

The monolithic `core_pack_builder.py` (793 LOC) is split into:
- `core_selector.py`: Select top 3000 words by frequency, validate NGSL + Oxford 3000 overlap
- `core_enricher.py`: Enrich each word, quality gate (definition, vi, IPA, example, topic)
- `core_exporter.py`: Write `core_3000.db` + indexes + `quality_report.md`

### 7.3 SQLite Export via DuckDB Bridge

```python
duck.execute(f"ATTACH '{sqlite_path}' AS output (TYPE sqlite)")
for table in export_tables:
    duck.execute(f"CREATE TABLE output.{table} AS SELECT * FROM main.{table}")
```

---

## 8. TUI Dashboard & Logging

### 8.1 Textual Dashboard Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  VOCAB CRAFT ENGINE — PIPELINE MONITOR                    HH:MM:SS  │
├──────────────┬───────────────────────────────────────────────────────┤
│   DAG VIEW   │              STEP TABLE                              │
│  (ASCII tree │  # │ Step       │ Status │ Progress  │ Time │ ETA   │
│  with color- │  ...with inline progress bars...                     │
│  coded node  │                                                      │
│  status)     │                                                      │
├──────────────┼──────────────────────────────────────────────────────┤
│  SYSTEM      │              LOG STREAM                              │
│  RAM/CPU/    │  Rich-formatted log output with step context         │
│  Disk/       │                                                      │
│  Throughput  │  ── Step Detail (selected step) ─────────────────── │
│              │  Rows inserted │ Batch # │ Checkpoint offset         │
│  TRANSLATION │  Source hash │ Error details                         │
│  Cache/Argos/│                                                      │
│  Google/Miss │                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

### 8.2 TUI Widgets

- **DAGPanel**: ASCII tree rendering with status icons (○ pending, ◌ waiting, ● running, ● success, ✖ failed, ⊘ skipped)
- **StepTable**: DataTable with inline progress bars (`████▒▒ 67%`) and ETA calculation
- **SystemPanel**: Real-time RAM, CPU, disk I/O, throughput (rows/sec), translation stats
- **StepDetail**: Click-to-expand detail view for selected step (rows, batch, checkpoint, errors)
- **RichLog**: Streaming log output with Rich markup formatting

### 8.3 Progress Reporting Protocol

Steps report progress via `ProgressReporter`:
```python
progress = ctx.create_progress(self.name, total=estimated_total)
for batch in self.stream():
    with progress.track_batch(len(batch)):
        process(batch)
```

### 8.4 Logging Architecture

Dual-format logging:
- **TUI**: Rich-formatted via `DashboardLogHandler` (INFO+)
- **File**: Plain text via `RotatingFileHandler` (DEBUG+, 50MB rotation, 5 backups)
- **Structured**: JSON Lines via `StructuredEventHandler` (INFO+, for analytics)

Log retention: 30 days, auto-cleanup on startup.

Log persistence: File-based per run (`logs/runs/run_YYYYMMDD_HHMMSS.json`) with `latest_run.json` symlink.

---

## 9. Project Structure

```
vocab-craft-engine/
├── config/
│   ├── settings.py
│   ├── pipeline_config.yaml      # NEW: DAG config, step toggles
│   └── theme_map.yaml
├── src/
│   ├── db/
│   │   ├── duckdb_manager.py     # NEW: DuckDB connection, batch ops, cache
│   │   └── schema.py             # NEW: DuckDB + SQLite schema definitions
│   ├── ingestion/
│   │   ├── base_ingestor.py      # NEW: streaming base class
│   │   ├── kaikki_ingestor.py
│   │   ├── tatoeba_ingestor.py
│   │   ├── opus_ingestor.py
│   │   ├── wordnet_ingestor.py   # NEW
│   │   └── sentence_filter.py
│   ├── transform/                # NEW module
│   │   ├── sentence_linker.py
│   │   ├── phrase_extractor.py
│   │   ├── relation_builder.py
│   │   └── topic_mapper.py
│   ├── enrichment/               # NEW module
│   │   ├── translation.py        # NEW: Argos + Google hybrid
│   │   ├── cefr_grader.py
│   │   ├── ipa_mapper.py
│   │   ├── vi_validator.py
│   │   ├── reflex_builder.py
│   │   └── scenario_builder.py
│   ├── export/
│   │   ├── sqlite_exporter.py    # NEW: DuckDB → SQLite bridge
│   │   ├── core_selector.py      # NEW: split from core_pack_builder
│   │   ├── core_enricher.py      # NEW: split from core_pack_builder
│   │   ├── core_exporter.py      # NEW: split from core_pack_builder
│   │   └── json_exporter.py      # NEW
│   ├── pipeline/
│   │   ├── core/
│   │   │   ├── base_step.py      # V2: depends_on, produces, optional
│   │   │   ├── dag.py            # NEW: DAG builder + topological sort
│   │   │   ├── orchestrator.py   # NEW: DAG-based parallel orchestrator
│   │   │   ├── context.py        # V2: DuckDB context
│   │   │   ├── result.py
│   │   │   └── state_manager.py  # V2: DuckDB-based state
│   │   ├── steps/                # Thin wrappers
│   │   │   ├── ingest_kaikki.py
│   │   │   ├── ingest_tatoeba.py
│   │   │   ├── ingest_opus.py
│   │   │   ├── ingest_wordnet.py
│   │   │   ├── transform_linking.py
│   │   │   ├── transform_phrases.py
│   │   │   ├── transform_relations.py
│   │   │   ├── enrich_translation.py
│   │   │   ├── enrich_reflex.py
│   │   │   ├── enrich_scenarios.py
│   │   │   ├── enrich_audio.py   # optional
│   │   │   ├── export_sqlite.py
│   │   │   ├── export_core3000.py
│   │   │   └── export_json.py
│   │   ├── cli.py                # V2: --force-step, --enable/--disable
│   │   └── monitor/
│   │       ├── dashboard.py      # V2: DAG-aware Textual TUI
│   │       ├── widgets.py        # NEW: DAGPanel, StepTable, SystemPanel
│   │       ├── progress.py       # NEW: ProgressReporter
│   │       ├── run_logger.py     # V2: structured + file logging
│   │       └── metrics.py
│   └── media/
│       ├── audio_generator.py
│       └── ipa_mapper.py
├── scripts/
│   └── download_raw_data.py      # Updated: + WordNet, Oxford 3000
├── tests/
│   ├── test_ingestion/
│   ├── test_transform/
│   ├── test_enrichment/
│   ├── test_export/
│   └── test_pipeline/
├── main.py
├── pyproject.toml
└── Makefile
```

---

## 10. Dependency Changes

```toml
# New dependencies
"argostranslate>=1.9.0"       # Offline EN→VI translation
"orjson>=3.9.0"               # Fast JSON parsing/serialization
"nltk>=3.8.0"                 # WordNet, CMU Pronouncing Dict

# Existing (keep)
"duckdb>=0.9.0"               # Staging DB (already in deps, now actively used)
"spacy>=3.7.0"                # NLP (lemmatization, dependency parsing)
"polars>=0.20.0"              # Fast CSV scanning
"edge-tts>=6.1.0"             # TTS audio (optional step)
"pydantic>=2.5.0"             # Data validation
"rich>=13.7.0"                # Rich text formatting
"textual>=0.70.0"             # TUI dashboard
"g2p-en>=2.1.0"               # Grapheme-to-phoneme (IPA fallback)
"PyYAML>=6.0"                 # Config parsing

# Keep as fallback
"deep-translator>=1.11.0"     # Google Translate (fallback only)

# Potentially remove
# "ijson" → replaced by orjson for Kaikki parsing
```

---

## 11. CLI Interface

```bash
# Standard run (auto-skip cached steps)
python main.py

# Select specific steps
python main.py --steps ingest_kaikki,ingest_wordnet

# Skip specific steps
python main.py --skip-steps enrich_audio

# Enable optional step
python main.py --enable audio_generation

# Force re-run a step (cascades to downstream)
python main.py --force-step ingest_kaikki

# Force re-run everything
python main.py --force-all

# Resume from last crash
python main.py --resume

# Preview execution plan
python main.py --dry-run

# Disable TUI (plain log output)
python main.py --no-tui

# Export only
python main.py --steps export_sqlite,export_core3000,export_json
```

---

## 12. Verification Plan

### Automated Tests

```bash
# Unit tests for each module
pytest tests/ -v

# Integration test: full pipeline with sample data
pytest tests/test_pipeline/test_integration.py -v

# DAG correctness test
pytest tests/test_pipeline/test_dag.py -v
```

### Manual Verification

1. Run full pipeline on real data, verify runtime < 2 hours
2. Verify `english_dataset.db` schema and data integrity
3. Verify `core_3000.db` quality report passes all gates
4. Verify `dataset.json` is valid and contains expected structure
5. Verify TUI dashboard displays correctly with parallel step execution
6. Verify resume works after simulated crash
7. Verify cache invalidation cascades correctly

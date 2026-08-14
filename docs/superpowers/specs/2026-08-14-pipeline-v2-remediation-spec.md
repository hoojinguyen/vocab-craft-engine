# Pipeline V2 — Codebase Audit Report & Phased Remediation Roadmap

## 1. Executive Summary

During the implementation of the **Pipeline V2 Redesign** (`feat/pipeline-v2-foundation`), an exhaustive audit was performed against the foundational design specification (`docs/superpowers/specs/2026-08-13-pipeline-redesign-design.md`). 

The audit revealed that while high-level abstractions were set up, several critical bugs, massive performance bottlenecks, concurrency oversights, and dummy/stub implementations were introduced. As a result:
- Ingestion took over **7 hours** (instead of the targeted ~20–25 minutes).
- Translation hung indefinitely for hours due to single-row synchronous HTTP fallback calls.
- Independent steps ran **sequentially** on a single thread instead of in parallel.
- Several core outputs were populated with dummy or unranked data.

This document serves as the single source of truth for the audit findings and the 4-phase remediation plan to restore full pipeline integrity, speed, and data quality.

---

## 2. Detailed Codebase Audit Findings

### 2.1 Orchestration & Concurrency
* **No Real Parallel Execution**: In `src/pipeline/core/orchestrator.py` (`_execute_levels`), execution levels are computed by the DAG, but the steps inside each level are executed sequentially in a single-threaded `for step in level:` loop. `ProcessPoolExecutor` and `asyncio.gather()` / `ThreadPoolExecutor` were omitted.
* **DuckDB Single-Writer Concurrency**: DuckDB connections are single-writer per file. Concurrent multi-process execution requires either thread-safe connection management, per-worker staging tables, or an asynchronous batch writer queue.
* **Optional Step Filtering Missing**: Steps marked `optional = True` (e.g. `enrich_audio`) run unconditionally without checking if `--enable` was provided in CLI arguments.

### 2.2 Database Staging & Performance
* **Severe `insert_batch` Bottleneck**: In `src/db/duckdb_manager.py`, `insert_batch()` executes `SELECT count(*)` twice (before and after every batch) across tables with millions of records, and uses `conn.executemany()` via row-by-row parameter binding instead of DuckDB Native Appender (`conn.appender()`) or PyArrow / Polars streaming inserts.
* **Schema Mismatch on `_pipeline_meta`**: `main.py` (`handle_status`) queries columns `items_processed, execution_time_seconds, updated_at`, whereas `schema.py` defines `row_count, duration_secs, completed_at`, causing CLI status commands to crash.

### 2.3 Ingestion Layer
* **WordNet Ingestor Hardcoding**: In `src/ingestion/wordnet_ingestor.py`, `word_id` is hardcoded as `1` for all synonyms and antonyms. WordNet definitions are not inserted into `definitions`, and hypernyms/hyponyms are ignored.
* **Tatoeba & OPUS Ingestors**: `tatoeba_ingestor.py` loads entire files into Python dictionaries in memory instead of utilizing `polars.scan_csv()`, and only extracts one-way links (`eng -> vie`), dropping reverse pairs.
* **Missing Supplementary Sources**: `SUBTLEX-US` (word frequency ranking), `NGSL` (core word validation), `Oxford 3000/5000`, and `CMU Pronouncing Dict` are not ingested, leaving `words.frequency_rank` and `words.cefr_level` as `NULL`.

### 2.4 Transform Layer
* **Sentence Linker**: In `src/transform/sentence_linker.py`, tokenization is done via naive `split()` without lemmatization (failing to match inflections like `running` -> `run`), and loads millions of pairs into Python memory at once rather than executing via DuckDB SQL joins or streaming chunks.
* **Phrase Extractor**: `src/transform/phrase_extractor.py` hardcodes only 5 phrasal verbs, ignoring all Kaikki idioms, collocations, and proverbs. It also generates invalid `phrase_id` values in `phrase_sentences`.
* **Relation Builder**: `src/transform/relation_builder.py` is a 9-line empty stub that simply returns row counts without deduplication, resolving `target_word_id`, or handling bidirectional links (`inverted=1`).
* **Topic Mapper**: `src/transform/topic_mapper.py` hardcodes only 15 words across 3 topics, discarding `config/theme_map.yaml` and WordNet hypernym hierarchies.

### 2.5 Enrichment Layer
* **Translation Bottleneck**: `src/enrichment/translation.py` iterates row-by-row, attempts offline Argos (which fails when models are missing), falls back to synchronous HTTP calls to Google Translate row-by-row, and executes individual `UPDATE` queries per row. `enrich_translation.py` also omits phrase translation.
* **Reflex & Scenario Builders**: `reflex_builder.py` creates dummy cloze questions with hardcoded distractors `["walk", "jump", "fly"]` and takes the sentence's first word as the answer. `scenario_builder.py` inserts 1 hardcoded tree with 1 dummy node.
* **Audio Generator Step**: `enrich_audio.py` is a stub returning 0 items without invoking TTS.

### 2.6 Export Layer
* **SQLite Exporter Missing Indexes**: `src/export/sqlite_exporter.py` exports tables via DuckDB `ATTACH` but does not create SQLite indexes, foreign keys, or run `VACUUM/ANALYZE`, failing query benchmarks.
* **Core 3000 Pack Builder Stubs**: `core_selector.py` executes an unranked `LIMIT 3000`, `core_enricher.py` returns `True` unconditionally, and `core_exporter.py` outputs a fake SQLite database with only the word `"run"`.
* **JSON Exporter Stub**: `src/export/json_exporter.py` writes a summary payload (`{"vocab_count": ...}`) instead of the full hierarchical dataset.

### 2.7 Configuration, Dependencies & Tests
* **Missing Dependencies**: `pyproject.toml` lacks `orjson`, `nltk`, `argostranslate`, `pyarrow`.
* **Missing Config**: `config/pipeline_config.yaml` was not created.
* **Duplicate Step Files**: `src/pipeline/steps/` contains duplicate files (both numbered `01_`–`15_` and unnumbered V2 step files).
* **Test Failures**: 21 unit/integration tests failing due to API changes and database file lock contention.

---

## 3. Phased Remediation Roadmap

To ensure rigorous quality control and avoid recurring bugs, the remediation is broken down into 4 sequential phases. Each phase requires comprehensive unit tests, benchmark validation, and explicit review before proceeding.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 1: DB Engine & High-Performance Ingestion Layer                  │
│ - DuckDB Appender / PyArrow bulk inserts (>100k rows/sec)              │
│ - Fix WordNet (no hardcoded IDs, add synset defs & relations)          │
│ - Optimize Kaikki (<20 min) & Tatoeba (Polars lazy scan, 2-way links)  │
│ - Ingest SUBTLEX-US, NGSL, Oxford 3000 into staging                     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ Phase 2: NLP Transforms & Enrichment Layer                             │
│ - SentenceLinker with lemmatization & DuckDB SQL joins                 │
│ - Full PhraseExtractor (Kaikki idioms, collocations, proverbs)        │
│ - RelationBuilder (dedup, bidirectional, target_word_id resolution)    │
│ - TopicMapper (theme_map.yaml + WordNet hypernym chains)               │
│ - HybridTranslator (batch offline Argos + bulk DB update)              │
│ - Real ReflexBuilder (CEFR-graded distractors) & ScenarioBuilder       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ Phase 3: Multi-Core Concurrency & Exporters                            │
│ - DAG Parallel Orchestrator (ProcessPool for CPU, Async for IO)        │
│ - DuckDB thread-safe / multi-worker staging architecture               │
│ - SQLite Exporter with full indexes, FK checks & <5ms query benchmark  │
│ - Core 3000 Pack Builder with quality gates & validation report        │
│ - Full JSON Exporter (hierarchical dataset.json via orjson)            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ Phase 4: TUI Dashboard, Cleanup & Final Verification                   │
│ - Textual Dashboard with DAGPanel, SystemPanel, StepDetail             │
│ - Remove duplicate legacy 01_.. step files                             │
│ - Update pyproject.toml and create pipeline_config.yaml                │
│ - 100% test pass rate & full pipeline benchmark verification           │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Phase 1: DB Engine & High-Performance Ingestion Layer
* **Key Tasks**:
  1. Refactor `DuckDBManager`:
     - Implement high-speed bulk ingestion via DuckDB Appender / PyArrow Table insertion.
     - Remove redundant `count(*)` calls in batch loops.
     - Standardize `_pipeline_meta` schema and align with `main.py status/reset`.
  2. Fix & Optimize Ingestors:
     - `WordNetIngestor`: Remove hardcoded `word_id: 1`, extract synsets, definitions, and relations.
     - `KaikkiIngestor`: Stream with `orjson` + DuckDB Appender to complete in < 20 min.
     - `TatoebaIngestor` & `OpusIngestor`: Implement `polars.scan_csv()`, handle bidirectional links (`eng <-> vie`), and apply sentence quality filters.
     - Frequency Ingestor: Load `SUBTLEX-US` and `NGSL` to populate `frequency_rank` and initial CEFR levels.
  3. Dependencies: Add `orjson`, `nltk`, `pyarrow`, `argostranslate` to `pyproject.toml`.
* **Acceptance Criteria**:
  - Ingesting all raw datasets completes in **< 25 minutes** total.
  - Table `words` contains valid `frequency_rank` and `source`.
  - Table `definitions` contains definitions from both Kaikki and WordNet.
  - Table `word_relations` has correctly resolved `word_id` mappings.
  - All ingestion tests pass.

---

### Phase 2: NLP Transforms & Enrichment Layer
* **Key Tasks**:
  1. Transform Layer:
     - `SentenceLinker`: Use lemmatization and DuckDB table joins/batch streaming for linking words to sentences.
     - `PhraseExtractor`: Extract all idioms, collocations, phrasal verbs, and proverbs from Kaikki raw data and link to sentences with valid DB IDs.
     - `RelationBuilder`: Merge WordNet and Kaikki relations, resolve `target_word_id`, and handle bidirectional links (`inverted = 1`).
     - `TopicMapper`: Re-integrate `config/theme_map.yaml` and WordNet hypernym chain taxonomy.
  2. Enrichment Layer:
     - `HybridTranslator`: Implement batch translation with pre-installed offline Argos models, fallback caching, and bulk DuckDB updates (translate both definitions and phrases).
     - `ReflexBuilder`: Generate real speed reaction drill cards with dynamic distractors sampled by CEFR level.
     - `ScenarioBuilder`: Generate branching dialogue trees.
     - `EnrichAudioStep`: Connect Edge-TTS generator for words/phrases when `--enable audio_generation` is set.
* **Acceptance Criteria**:
  - Transforms execute in **< 15 minutes**.
  - `phrases` table contains thousands of categorized expressions.
  - `word_relations` contains deduplicated relations with resolved `target_word_id`.
  - `word_topics` maps words to curated themes.
  - Definitions and phrases have Vietnamese translations without blocking the pipeline.

---

### Phase 3: Multi-Core Concurrency & Exporters
* **Key Tasks**:
  1. Concurrency Architecture:
     - Upgrade `PipelineOrchestrator` to execute CPU-bound steps in `ProcessPoolExecutor` and IO-bound steps in `asyncio` / `ThreadPoolExecutor`.
     - Implement thread-safe DuckDB connection handling / worker staging to avoid database locks.
     - Honor `optional = True` steps based on CLI `--enable` flags.
  2. Export Pipeline:
     - `SQLiteExporter`: ATTACH DuckDB to SQLite, copy tables, generate all indexes (`idx_words_lemma`, `idx_definitions_word_id`, `idx_phrases_type`, etc.), enforce FK integrity, and run `VACUUM/ANALYZE`. Ensure reflex drill query speed < 5ms.
     - `CorePackBuilder`: Decompose into `CoreSelector` (top 3000 by SUBTLEX/NGSL), `CoreEnricher` (quality gates for IPA, definition_vi, example, topic), and `CoreExporter` (`core_3000.db` + `quality_report.md`).
     - `JsonExporter`: Generate full hierarchical `dataset.json` via `orjson`.
* **Acceptance Criteria**:
  - Independent steps within DAG levels run concurrently across multiple CPU cores.
  - `english_dataset.db` passes foreign key verification and < 5ms query benchmark.
  - `core_3000.db` contains exactly 3,000 top words passing all quality gates.
  - `dataset.json` contains full nested vocabulary data.

---

### Phase 4: TUI Dashboard, Cleanup & Final Verification
* **Key Tasks**:
  1. TUI Monitor:
     - Build `DAGPanel` (ASCII dependency tree with real-time status indicators).
     - Build `SystemPanel` (RAM, CPU, disk I/O, throughput rows/sec).
     - Build `StepDetail` (expandable view for active/completed step metrics).
  2. Cleanup & Configuration:
     - Delete obsolete duplicate numbered step files (`src/pipeline/steps/01_...` to `15_...`).
     - Create `config/pipeline_config.yaml` with step toggles and memory/thread parameters.
  3. Verification:
     - Fix all broken tests across the entire test suite.
     - Run end-to-end integration and performance benchmark on full dataset.
* **Acceptance Criteria**:
  - Full pipeline completes end-to-end in **~1 - 1.5 hours**.
  - All 15 DAG steps succeed and can resume gracefully from checkpoints.
  - 100% test pass rate with zero test failures.

# Phase-by-Phase Execution Plan

## Objective Overview

Build a production-grade **VocabCraft Engine** pipeline automating raw data ingestion (Kaikki, Tatoeba, OPUS), NLP enrichment (Lemmatization, CEFR grading, Collocations, Reflex Drills, Dialogue Trees), dual-speed neural audio synthesis (Edge-TTS), and packaging into a high-performance offline **SQLite database (`english_dataset.db`)** (< 5ms query response) with complete developer documentation.

---

## Phase 1: Project Setup & Infrastructure

### 1.1 Directory Structure Initialization
Initialize standard Python package structure:
```
vocab-craft-engine/
├── config/                  # Configuration & Environment Settings
│   └── settings.py
├── data/                    # Local storage (GitIgnored)
│   ├── raw/                 # Kaikki JSON, Tatoeba CSV, OPUS
│   ├── processed/           # Intermediate DuckDB / Parquet
│   ├── audio/               # Generated MP3s (1.0x & 1.2x)
│   └── output/              # Final packaged english_dataset.db
├── docs/                    # Architecture & Guides
│   ├── dataset_system_architecture.md
│   ├── execution_plan.md
│   └── mobile_integration_guide.md
├── src/
│   ├── ingestion/           # Streaming Parsers (Kaikki, Tatoeba, OPUS)
│   ├── nlp/                 # Lemmatizer, CEFR Grader, Collocations, Reflex & Tree Builder
│   ├── media/               # Edge-TTS Synthesizer & IPA Mapper
│   ├── db/                  # Database Manager & Transactions
│   └── export/              # SQLite Exporter & Indexing Optimizer
├── tests/                   # Pytest Validation Suite
├── Makefile                 # Automation Makefile
├── pyproject.toml           # Package configuration & dependencies
└── README.md
```

### 1.2 Dependency Management (`pyproject.toml`)
- Configured dependencies:
  - `spacy>=3.7.0` (Deterministic NLP processing)
  - `ijson>=3.2.0` (Stream parsing large JSON dumps)
  - `duckdb>=0.9.0` (Fast staging database)
  - `edge-tts>=6.1.0` (Free Neural TTS engine)
  - `polars>=0.20.0` (High-performance DataFrame processing)
  - `pytest>=8.0.0` & `pytest-asyncio` (Automated testing suite)
- spaCy model installation: `python -m spacy download en_core_web_sm`.

### 1.3 Settings Configuration (`config/settings.py`)
- Configured key runtime constants: `BATCH_SIZE = 1000`, `MAX_CONCURRENT_AUDIO = 5`, `TARGET_REFLEX_TIME_MS = 2500`.
- Pathlib-based relative path management.

---

## Phase 2: Ingestion Layer

### 2.1 Kaikki JSON Streaming Parser (`src/ingestion/kaikki_parser.py`)
- Uses `ijson` to stream records from `kaikki.org-dictionary-English.json`.
- Extracts: `word`, `pos`, `senses` (definitions & examples), `sounds` (IPA UK/US).

### 2.2 Tatoeba Parallel Corpus Parser (`src/ingestion/tatoeba_parser.py`)
- Reads `sentences.csv` & `links.csv`.
- Extracts aligned parallel sentence pairs (`text_en`, `text_vi`).
- Filters out corrupt or overly long (> 30 words) sentences.

### 2.3 OPUS Dialogue Parser (`src/ingestion/opus_parser.py`)
- Mines short dialogue turns (2 – 10 words) to feed interactive branching trees (`dialogue_nodes`).

### 2.4 Staging Database Manager (`src/db/staging_db.py`)
- Manages DuckDB/SQLite connections with **Transaction batching** (`BEGIN` ... `COMMIT` every 1,000 records).
- Idempotent execution using `INSERT OR IGNORE` on `UNIQUE` keys (`words.lemma`, `sentences.text_en`).

---

## Phase 3: NLP Enrichment & Reflex Drill Generation

### 3.1 Lemmatizer & POS Tagger (`src/nlp/lemmatizer.py`)
- Uses `spaCy.pipe` batch processing (500 sentences/batch) for RAM efficiency.
- Populates `word_sentence_map`.

### 3.2 Automated CEFR Difficulty Grader (`src/nlp/cefr_grader.py`)
- Ingests SUBTLEX-US frequency rankings.
- Computes difficulty scores and assigns CEFR levels (A1, A2, B1, B2, C1, C2) to words and sentences.

### 3.3 Collocation & Chunk Extractor (`src/nlp/chunk_extractor.py`)
- Mines `Verb + Noun` (e.g., *take a break*) and `Verb + Preposition` (e.g., *look for*) collocations via spaCy dependency parsing.

### 3.4 Speed Reflex Drill Generator (`src/nlp/reflex_builder.py`)
- Scans sentence pool, extracts `correct_answer`, and pre-generates 3 distractor choices in JSON array payloads.

### 3.5 Scenario Tree Generator (`src/nlp/scenario_builder.py`)
- Assembles conversational dialogue turns into branching trees (`dialogue_trees` & `dialogue_nodes`).

---

## Phase 4: Media & Audio Synthesis Pipeline

### 4.1 Phonetic & IPA Mapper (`src/media/ipa_mapper.py`)
- Maps Kaikki IPA transcriptions with `g2p_en` fallback for out-of-vocabulary terms.

### 4.2 Batch Neural Audio Synthesizer (`src/media/audio_generator.py`)
- Uses `edge-tts` with `asyncio.Semaphore(5)` to produce `.mp3` files at dual speeds:
  - `Standard (1.0x)` for vocabulary and sentence cards.
  - `Fast Reflex (1.2x)` for reaction speed exercises.
- Exponential backoff retry handler (3 retries on network timeout).

---

## Phase 5: SQLite Packaging & Verification

### 5.1 Mobile SQLite Exporter (`src/export/sqlite_exporter.py`)
- Packages staged tables into `english_dataset.db`.
- Optimizes SQLite PRAGMAs (`journal_mode = WAL`, `synchronous = NORMAL`).
- Creates multi-column composite indexes (`idx_words_lemma`, `idx_reflex_cefr_type`, `idx_nodes_tree_parent`).

### 5.2 Automated Verification Suite (`tests/`)
- `tests/test_schema.py`: Verifies foreign key constraints (`PRAGMA foreign_key_check`).
- `tests/test_performance.py`: Benchmarks reflex drill query latency (< 5ms).

### 5.3 Mobile Integration Documentation (`docs/mobile_integration_guide.md`)
- Provides code examples for iOS (SwiftData/FMDB), Android (Room), React Native (expo-sqlite), and Flutter (sqflite).

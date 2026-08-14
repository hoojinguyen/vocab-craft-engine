# 🚀 VocabCraft Engine (Pipeline V2)

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Database: DuckDB & SQLite](https://img.shields.io/badge/database-DuckDB%20%7C%20SQLite-brightgreen.svg)](https://duckdb.org/)
[![TUI: Textual](https://img.shields.io/badge/TUI-Textual-purple.svg)](https://textual.textualize.io/)

**VocabCraft Engine** is an industrial-grade ETL, linguistic enrichment, CEFR grading, multi-tier IPA phonetic mapping, Vietnamese translation, and mobile-ready SQLite packaging engine designed to build rich, offline-first English learning datasets for iOS, Android, Flutter, and React Native.

---

## ⚡ Key Capabilities & Pipeline V2 Highlights

* **15-Step DAG Pipeline**: Directed Acyclic Graph orchestrator with automatic dependency resolution, stage caching, resume-on-failure, and selective execution.
* **DuckDB Analytical Staging**: In-memory / embedded OLAP staging (`staging.duckdb`) processing millions of lexical records with fast batch ingestion and zero-copy queries.
* **Curated Core 3000 Pack & 5 Quality Gates**:
  * Frequency-ranked word selection from `SUBTLEX-US` with POS noise filtering and contraction expansion.
  * Rigorous 5 Quality Gates (EN definition length, validated Vietnamese translation via `VietnameseValidator`, IPA phonetics, contextual sentence links, and thematic topic mapping).
  * Automated generation of `quality_report.md` with NGSL and Oxford 3000 overlap statistics.
* **Multi-Tier IPA Phonetic Engine**:
  * **Tier 0**: DuckDB `_ipa_cache` instant lookup.
  * **Tier 1**: Kaikki Wiktionary UK & US phonetic pronunciations.
  * **Tier 2**: NLTK CMU Pronouncing Dictionary (`cmudict`) with ARPAbet-to-IPA conversion.
  * **Tier 3**: `g2p-en` Neural Grapheme-to-Phoneme model fallback.
* **Offline Vietnamese Translation Engine**: High-throughput `ArgosTranslate` neural machine translation with fallback validation preventing English passthroughs.
* **Interactive Terminal UI (TUI)**: Real-time Textual dashboard (`src/monitoring/tui/`) streaming pipeline progress, resource telemetry (CPU %, RAM, speed, ETA), step tables, and live logs.
* **Dual-Speed Neural Audio**: Edge-TTS audio synthesis (Standard 1.0x & Fast Reflex 1.2x) with concurrency throttling and retry backoff.
* **Mobile-Optimized SQLite & JSON**: Packaged `english_dataset.db` and `core_3000.db` (< 5ms query latency) with composite indexing, WAL mode, foreign key integrity, and checksum validation.

---

## 🏗️ System Architecture

```
                                  DATA SOURCES
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Kaikki.org | Tatoeba | OpenSubtitles | EnViCorpora | WordNet | SUBTLEX │
   │                  NGSL 1.01 | Oxford 3000 / 5000 Wordlists              │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                       INGESTION & STAGING (DuckDB)
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Ingest Kaikki ──> Ingest WordNet ──> Ingest Frequency ──> Ingest Sents │
   │ └── Staging Tables: words, definitions, sentences, _ipa_cache          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                       TRANSFORMATION & ENRICHMENT
   ┌────────────────────────────────────────────────────────────────────────┐
   │ • Translate Definitions (ArgosTranslate + VietnameseValidator)         │
   │ • Multi-Tier IPA Mapping (DuckDB Cache ➔ Kaikki ➔ CMU Dict ➔ g2p-en)   │
   │ • Spacy POS Tagging & Collocation Mining                               │
   │ • Sentence-Word Linking & 18-Curated Theme Taxonomy Mapping            │
   │ • High-Speed Reflex Drills (< 2.5s) & Interactive Dialogue Trees       │
   │ • Dual-Speed Neural Audio Generation (Edge-TTS)                        │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                       EXPORT, AUDIT & PACKAGING
   ┌────────────────────────────────────────────────────────────────────────┐
   │ • SQLite Exporter (english_dataset.db)                                 │
   │ • Core 3000 Exporter (core_3000.db + data/output/quality_report.md)    │
   │ • JSON Exporter (Hierarchical & Flat JSON bundles)                     │
   │ • Verifier & ZIP Packager (SHA-256 Checksums)                          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                              TUI MONITOR (Textual)
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Live Status Header | Step Table | Telemetry Card | Streaming RichLog   │
   └────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
vocab-craft-engine/
├── config/
│   ├── settings.py                  # Paths, constants, and directory configurations
│   ├── pipeline_config.yaml         # Concurrency, batch sizes, and step defaults
│   └── theme_map.yaml               # 18 curated topic taxonomy mapping rules
├── data/
│   ├── raw/                         # Downloaded raw source files (JSON, CSV, TXT)
│   ├── processed/                   # DuckDB staging database (staging.duckdb)
│   ├── audio/                       # Generated dual-speed MP3 audio files
│   └── output/                      # Packaged databases (english_dataset.db, core_3000.db)
├── docs/
│   ├── superpowers/                 # Architecture design specs & phase implementation plans
│   ├── dataset_system_architecture.md
│   └── mobile_integration_guide.md
├── scripts/
│   ├── download_raw_data.py         # Downloader for Kaikki, Tatoeba, Oxford, NLTK, NGSL
│   ├── benchmark_pipeline.py        # Performance benchmarking suite
│   └── migrate_sqlite_to_duckdb.py  # Staging migration utilities
├── src/
│   ├── db/                          # DuckDBManager & transactional database helpers
│   ├── enrichment/                  # Translation engine, validator, collocations, reflex
│   ├── export/                      # CoreSelector, CoreEnricher, CoreExporter, JSON exporter
│   ├── ingestion/                   # Streaming parsers for Kaikki, WordNet, OPUS, Tatoeba
│   ├── media/                       # Multi-Tier IPAMapper & AudioGenerator
│   ├── monitoring/                  # Textual TUI widgets & PipelineProgressApp
│   ├── nlp/                         # Spacy pipeline & Theme / TopicMapper
│   ├── pipeline/                    # DAG orchestrator, 15 step classes, CLI runner
│   └── transform/                   # Sentence linker, relation builders, POS tagger
├── tests/                           # 230+ automated pytest suite
├── main.py                          # Unified CLI entry point
└── pyproject.toml                   # Project dependencies and configurations
```

---

## 🛠️ Quick Start Guide

### 1. Prerequisites & Installation

Requires **Python 3.14+**. We recommend using `.venv`:

```bash
# Clone the repository
git clone https://github.com/hoojinguyen/vocab-craft-engine.git
cd vocab-craft-engine

# Initialize virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Download Raw Datasets

Download raw source datasets (Kaikki Wiktionary, Tatoeba, Oxford 3000, NLTK WordNet/CMUDict, SUBTLEX):

```bash
python scripts/download_raw_data.py
```

### 3. Run the Pipeline

#### Standard Run with Interactive TUI Monitor
```bash
python main.py --tui
```

#### Headless Mode with Plain Logging
```bash
python main.py --no-tui
```

#### Run Specific Steps
```bash
python main.py --steps ingest_kaikki,ingest_wordnet,export_core3000
```

#### Preview Execution Plan (Dry Run)
```bash
python main.py --dry-run
```

#### Force Re-run a Step (Cascades Downstream)
```bash
python main.py --force-step export_core3000
```

#### Check Current Pipeline Status
```bash
python main.py --status
```

---

## 💻 CLI Reference Options

| Flag | Description | Default |
|---|---|:---:|
| `--tui` / `--no-tui` | Toggle interactive Textual TUI vs plain terminal logs | `--no-tui` |
| `--steps <s1,s2>` | Comma-separated list of specific pipeline steps to execute | All steps |
| `--skip-steps <s1,s2>` | Comma-separated list of steps to bypass | None |
| `--force-step <step>` | Force re-run a specific step and its downstream dependents | None |
| `--force-all` | Clear all checkpoints and re-execute entire pipeline | `False` |
| `--resume` | Resume execution from the last recorded checkpoint | `False` |
| `--dry-run` | Print the resolved DAG topological execution order without executing | `False` |
| `--workers <N>` | Number of concurrent worker threads/processes | `4` |
| `--status` | Display tabular execution status of all 15 pipeline steps | `False` |

---

## 📊 15 Pipeline Steps (DAG Flow)

```
 1. ingest_kaikki        ──> Stream-parse Wiktionary headwords & definitions
 2. ingest_wordnet       ──> Ingest WordNet synsets & semantic definitions
 3. ingest_freq          ──> Ingest SUBTLEX-US frequency rankings
 4. ingest_sentences     ──> Ingest Tatoeba & parallel bilingual sentence corpora
 5. tag_pos              ──> SpaCy POS tagging & morphological normalization
 6. translate_defs       ──> ArgosTranslate neural EN ➔ VI definition translation
 7. enrich_ipa           ──> Multi-tier IPA phonetics resolution & caching
 8. link_sentences       ──> Link contextual sentences to headwords
 9. map_topics           ──> Map raw categories into 18 curated themes
10. transform_relations  ──> Build bidirectional synonyms, antonyms & hyponyms
11. build_reflex         ──> Generate high-speed reflex choices (< 2.5s drills)
12. enrich_audio         ──> Edge-TTS dual-speed neural audio generation (Optional)
13. export_sqlite        ──> Pack complete mobile database (english_dataset.db)
14. export_core3000      ──> Build curated Core 3000 pack & quality_report.md
15. export_json          ──> Build hierarchical JSON distributions
```

---

## 🧪 Testing & Verification

Run the comprehensive automated test suite (230+ tests):

```bash
# Run all unit and integration tests
./.venv/bin/pytest tests/ -v

# Run export & quality gate tests
./.venv/bin/pytest tests/test_export/ -v

# Run TUI monitoring tests
./.venv/bin/pytest tests/test_monitoring/ -v

# Run media & multi-tier IPA mapper tests
./.venv/bin/pytest tests/test_media/ -v
```

---

## 📱 Mobile Integration

For integration guides on embedding `core_3000.db` and `english_dataset.db` into iOS (SwiftData / GRDB), Android (Room), Flutter (sqflite), and React Native (expo-sqlite), see 📄 **[docs/mobile_integration_guide.md](docs/mobile_integration_guide.md)**.

---

## 📄 License

MIT License © 2026 VocabCraft Engine Team.

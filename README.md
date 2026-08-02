# VocabCraft Engine

An automated ETL, linguistic enrichment, CEFR grading, dual-speed neural audio synthesis, and mobile-ready SQLite packaging engine for English learning applications (iOS, Android, Flutter, React Native).

---

## ⚡ Core Features

- **Automated Data Ingestion:** Stream-parse Wiktionary (Kaikki.org), Tatoeba parallel corpora, and OPUS subtitle dialogues without loading multi-gigabyte dumps into RAM.
- **Linguistic Enrichment & NLP:** SpaCy-powered lemmatization, dependency-based collocation mining, and automatic sentence pattern extraction.
- **Automated CEFR Grading:** Statistical difficulty scoring based on SUBTLEX-US word frequency rankings.
- **Interactive Scenarios & Speed Reflex Drills:** Generates pre-computed distractor choices for high-speed reaction cards (< 2.5s) and branching dialogue trees.
- **Dual-Speed Neural Audio:** Neural TTS audio synthesis (Standard 1.0x & Fast Reflex 1.2x) via Edge-TTS with exponential backoff retries.
- **Mobile SQLite Packaging:** High-performance offline database (< 5ms query response) with composite indexing, WAL mode, and complete foreign key integrity.

---

## 🚀 Project Architecture

```
vocab-craft-engine/
├── config/                  # Environment & settings configuration (settings.py)
├── data/                    # Storage for raw datasets, intermediate staging & output
│   ├── raw/                 # Kaikki JSON dumps, Tatoeba CSVs, OPUS subtitles
│   ├── processed/           # Staging database directory
│   ├── audio/               # Generated MP3 audio files (1.0x & 1.2x)
│   └── output/              # Final packaged english_dataset.db
├── docs/                    # System architecture & integration documentation
│   ├── dataset_system_architecture.md
│   ├── execution_plan.md
│   ├── mobile_integration_guide.md
│   ├── pre_ai_language_data_architecture.md
│   └── setup_guide.md
├── scripts/                 # Utility scripts & dataset downloaders
├── src/                     # Core engine package
│   ├── ingestion/           # Streaming parsers (Kaikki, Tatoeba, OPUS)
│   ├── nlp/                 # Lemmatizer, CEFR grader, collocations, reflex engine
│   ├── media/               # Edge-TTS audio synthesizer & IPA mapper
│   ├── db/                  # Staging connection & transaction manager
│   └── export/              # Mobile SQLite packager & index optimizer
├── tests/                   # Automated test suite (pytest)
├── Makefile                 # Build automation Makefile
├── main.py                  # CLI pipeline runner
├── pyproject.toml           # Project dependencies & package configuration
└── README.md
```

---

## 🛠️ Quick Start Guide

```bash
# 1. Initialize virtual environment and install all dependencies automatically
make setup

# 2. Download raw datasets (Kaikki Wiktionary & Tatoeba parallel sentences)
make download-data

# 3. Execute the full ETL & NLP enrichment pipeline
make run

# 4. Run the automated test suite
make test
```

For comprehensive installation and workflow details, see 📄 **[docs/setup_guide.md](docs/setup_guide.md)**.

---

## 📱 Mobile Integration

For instructions on embedding `english_dataset.db` into iOS (SwiftData/FMDB), Android (Room), Flutter (sqflite), and React Native (expo-sqlite), consult the 📄 **[docs/mobile_integration_guide.md](docs/mobile_integration_guide.md)**.

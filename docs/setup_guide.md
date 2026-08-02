# Environment Setup & Pipeline Execution Guide

This document provides step-by-step instructions for setting up the Python environment, downloading raw linguistic datasets, running the automated ETL pipeline, and verifying system health for **VocabCraft Engine**.

---

## 1. Prerequisites

- **Python 3.11+**
- **GNU Make** (`make`)
- **Git**

---

## 2. Automated Environment Setup

Run the following command in the project root to create the Python virtual environment (`.venv`), install dependencies, and download required spaCy / NLTK models:

```bash
make setup
```

---

## 3. Downloading Raw Datasets

To download raw open-source datasets (Kaikki Wiktionary 3.18GB dump & Tatoeba parallel sentence pairs) into `data/raw/`:

```bash
make download-data
```

---

## 4. Pipeline Execution & Database Packaging

To run the complete 5-step ETL and linguistic enrichment pipeline with real-time progress logging:

```bash
make run
```

### Pipeline Execution Output

The pipeline displays progress logs for each milestone:
- `[Step 1/5] Initializing SQLite Database Schema...`
- `[Step 2/5] Ingesting Kaikki Dictionary (3.18 GB dump)...`
  - `-> Processed 50,000 dictionary entries...`
  - `-> Processed 100,000 dictionary entries...`
- `[Step 3/5] Ingesting Tatoeba Parallel Sentences...`
- `[Step 4/5] Running NLP Enrichment (Collocations, Scenarios, Reflex Drills)...`
- `[Step 5/5] Packaging & Optimizing SQLite Mobile Database...`

To force a clean rebuild from scratch (bypassing step auto-resume checkpoints):

```bash
make run-fresh
```

---

## 5. Running Automated Tests

To execute the automated test suite and ensure pipeline integrity:

```bash
make test
```

# ==============================================================================
# Makefile for VocabCraft Engine
# ==============================================================================

PYTHON_SYS ?= $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3.13 2>/dev/null || (test -x ~/.local/bin/uv && ~/.local/bin/uv python find 3.12 2>/dev/null) || (command -v uv 2>/dev/null && uv python find 3.12 2>/dev/null) || command -v python3 2>/dev/null)
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
PYTEST = $(VENV_DIR)/bin/pytest

# NLTK 3.10.1 import security blocks any package that resolves inside the CWD.
# Since .venv lives inside the repo, everything is blocked (false positive).
export NLTK_DISABLE_IMPORT_SECURITY := 1

.PHONY: help setup download-data corpus-download run run-fresh run-step benchmark test clean clean-db

help:
	@echo "========================================================================"
	@echo "                      VOCABCRAFT ENGINE COMMANDS                        "
	@echo "========================================================================"
	@echo "  make setup          : Set up Python virtualenv & install dependencies"
	@echo "  make download-data  : Download raw datasets (Kaikki & Tatoeba)"
	@echo "  make corpus-download: Download parallel corpora (OpenSubtitles + EnViCorpora)"
	@echo "  make run            : Smart auto-resume run (skips completed ingest steps)"
	@echo "  make run-fresh      : Force re-ingest everything from scratch"
	@echo "  make test           : Run full automated pytest test suite"
	@echo "  make clean-db       : Delete output SQLite database file"
	@echo "  make clean          : Remove virtual environment and temporary caches"
	@echo "========================================================================"

setup:
	@echo "==> Creating virtual environment in $(VENV_DIR) using $(PYTHON_SYS)..."
	@$(PYTHON_SYS) -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' || (echo "ERROR: Python >= 3.11 is required. Current version is $$($(PYTHON_SYS) --version)"; exit 1)
	$(PYTHON_SYS) -m venv $(VENV_DIR)
	@echo "==> Upgrading pip & installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo "==> Downloading spaCy English model (en_core_web_sm)..."
	$(PYTHON) -m spacy download en_core_web_sm
	@echo "==> Downloading NLTK tagger data..."
	$(PYTHON) -c "import nltk; nltk.download('averaged_perceptron_tagger_eng')"
	@echo "==> Setup completed successfully!"

download-data:
	@echo "==> Downloading raw datasets (Kaikki Wiktionary & Tatoeba sentences)..."
	$(PYTHON) scripts/download_raw_data.py

corpus-download:
	@echo "==> Downloading parallel corpora (OpenSubtitles + EnViCorpora)..."
	$(PYTHON) -c "from scripts.download_raw_data import download_opensubtitles_envi, download_envicorpora; download_opensubtitles_envi(); download_envicorpora()"
	@echo "==> Corpora downloaded to data/raw/opensubtitles_envi/ and data/raw/envicorpora/"

run:
	@echo "==> Starting English Dataset ETL Pipeline (Smart Auto-Resume)..."
	$(PYTHON) main.py

run-fresh:
	@echo "==> Starting English Dataset ETL Pipeline (Force Re-ingest)..."
	$(PYTHON) main.py --force-reset

run-step:
	@echo "==> Running pipeline stage: $(STEP)..."
	$(PYTHON) main.py --stage $(STEP)

benchmark:
	@echo "==> Running benchmark..."
	time $(PYTHON) main.py --force-reset

.PHONY: core-pack

core-pack:
	@echo "==> Building Core 3000 Word Pack..."
	$(PYTHON) main.py --build-core-pack
	@echo "==> Core pack written to data/output/core_pack/"

test:
	@echo "==> Running Pytest test suite..."
	$(PYTEST) -v

benchmark-ingest:
	@echo "==> Benchmarking Kaikki SQL ingest (full dump)..."
	$(PYTEST) tests/test_kaikki_sql_benchmark.py -v -s -m slow

clean-db:
	@echo "==> Deleting old output databases..."
	rm -f data/output/english_dataset.db data/output/english_dataset.db-wal data/output/english_dataset.db-shm
	rm -f data/processed/staging.duckdb data/processed/staging.duckdb.wal
	rm -f data/processed/sentence_link_checkpoint.json
	rm -f data/processed/checkpoint_*.json
	@echo "==> Databases and checkpoints deleted."

clean:
	@echo "==> Cleaning virtualenv and build caches..."
	rm -rf $(VENV_DIR) .pytest_cache *.egg-info build dist
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "==> Clean complete."

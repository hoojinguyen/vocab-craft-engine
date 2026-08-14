# ==============================================================================
# Makefile for VocabCraft Engine
# ==============================================================================

PYTHON_SYS ?= $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3.13 2>/dev/null || command -v python3.14 2>/dev/null || (test -x ~/.local/bin/uv && ~/.local/bin/uv python find 3.12 2>/dev/null) || (command -v uv >/dev/null 2>&1 && uv python find 3.12 2>/dev/null) || command -v python3 2>/dev/null)
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
PYTEST = $(VENV_DIR)/bin/pytest

# NLTK 3.10.1 import security blocks any package that resolves inside the CWD.
# Since .venv lives inside the repo, everything is blocked (false positive).
export NLTK_DISABLE_IMPORT_SECURITY := 1

.PHONY: help setup download-data corpus-download run run-fresh test clean clean-db

help:
	@echo "========================================================================"
	@echo "                      VOCABCRAFT ENGINE COMMANDS (V2)                   "
	@echo "========================================================================"
	@echo "  make setup          : Set up Python virtualenv & install dependencies"
	@echo "  make download-data  : Download raw datasets (Kaikki, Tatoeba, Oxford, NGSL)"
	@echo "  make corpus-download: Download parallel corpora (OpenSubtitles + EnViCorpora)"
	@echo "  make run            : Standard pipeline run with console logging"
	@echo "  make run-tui        : Pipeline run with interactive Terminal UI dashboard"
	@echo "  make run-fresh      : Force re-run entire pipeline from scratch"
	@echo "  make status         : Show execution status of all 15 pipeline steps"
	@echo "  make dry-run        : Preview resolved 15-step DAG execution plan"
	@echo "  make core-3000      : Export curated Core 3000 SQLite pack & quality report"
	@echo "  make test           : Run full automated pytest test suite"
	@echo "  make clean-db       : Delete staging and output databases"
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
	$(PYTHON) -c "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('wordnet'); nltk.download('cmudict')"
	@echo "==> Setup completed successfully!"

download-data:
	@echo "==> Downloading raw datasets (Kaikki, Tatoeba, Oxford 3000, NLTK, NGSL)..."
	$(PYTHON) scripts/download_raw_data.py

corpus-download:
	@echo "==> Downloading parallel corpora (OpenSubtitles + EnViCorpora)..."
	$(PYTHON) -c "from scripts.download_raw_data import download_opensubtitles_envi, download_envicorpora; download_opensubtitles_envi(); download_envicorpora()"
	@echo "==> Corpora downloaded to data/raw/opensubtitles_envi/ and data/raw/envicorpora/"

run:
	@echo "==> Starting VocabCraft Engine Pipeline V2 (Headless Console)..."
	$(PYTHON) main.py --no-tui

run-tui:
	@echo "==> Starting VocabCraft Engine Pipeline V2 (Interactive Terminal UI)..."
	$(PYTHON) main.py --tui

dry-run:
	@echo "==> Previewing VocabCraft Pipeline V2 DAG Execution Plan..."
	$(PYTHON) main.py --dry-run

status:
	@echo "==> Checking VocabCraft Pipeline V2 Steps Status..."
	$(PYTHON) main.py --status

resume:
	@echo "==> Resuming VocabCraft Pipeline V2 from last recorded checkpoint..."
	$(PYTHON) main.py --resume

run-fresh:
	@echo "==> Starting VocabCraft Pipeline V2 (Force Re-run All Steps)..."
	$(PYTHON) main.py --force-all

core-3000:
	@echo "==> Building Curated Core 3000 Word Pack & Quality Report..."
	$(PYTHON) main.py --steps export_core3000
	@echo "==> Core 3000 bundle written to data/output/core_3000.db and quality_report.md"

test:
	@echo "==> Running Pytest test suite..."
	$(PYTEST) -v

clean-db:
	@echo "==> Deleting old staging and output database files..."
	rm -f data/output/english_dataset.db data/output/core_3000.db data/output/quality_report.md
	rm -f data/processed/staging.duckdb
	rm -f data/processed/sentence_link_checkpoint.json
	@echo "==> Staging and output databases successfully deleted."

clean:
	@echo "==> Cleaning virtualenv and build caches..."
	rm -rf $(VENV_DIR) .pytest_cache *.egg-info build dist
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "==> Clean complete."

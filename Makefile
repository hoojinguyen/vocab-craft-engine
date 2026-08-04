# ==============================================================================
# Makefile for VocabCraft Engine
# ==============================================================================

VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
PYTEST = $(VENV_DIR)/bin/pytest

# NLTK 3.10.1 import security blocks any package that resolves inside the CWD.
# Since .venv lives inside the repo, everything is blocked (false positive).
export NLTK_DISABLE_IMPORT_SECURITY := 1

.PHONY: help setup download-data run run-fresh test clean clean-db

help:
	@echo "========================================================================"
	@echo "                      VOCABCRAFT ENGINE COMMANDS                        "
	@echo "========================================================================"
	@echo "  make setup          : Set up Python virtualenv & install dependencies"
	@echo "  make download-data  : Download raw datasets (Kaikki & Tatoeba)"
	@echo "  make run            : Smart auto-resume run (skips completed ingest steps)"
	@echo "  make run-fresh      : Force re-ingest everything from scratch"
	@echo "  make test           : Run full automated pytest test suite"
	@echo "  make clean-db       : Delete output SQLite database file"
	@echo "  make clean          : Remove virtual environment and temporary caches"
	@echo "========================================================================"

setup:
	@echo "==> Creating virtual environment in $(VENV_DIR)..."
	python3 -m venv $(VENV_DIR)
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

run:
	@echo "==> Starting English Dataset ETL Pipeline (Smart Auto-Resume)..."
	$(PYTHON) main.py

run-fresh:
	@echo "==> Starting English Dataset ETL Pipeline (Force Re-ingest)..."
	$(PYTHON) main.py --force-reset

test:
	@echo "==> Running Pytest test suite..."
	$(PYTEST) -v

clean-db:
	@echo "==> Deleting old output SQLite database file..."
	rm -f data/output/english_dataset.db data/output/english_dataset.db-wal data/output/english_dataset.db-shm
	@echo "==> Old SQLite database successfully deleted."

clean:
	@echo "==> Cleaning virtualenv and build caches..."
	rm -rf $(VENV_DIR) .pytest_cache *.egg-info build dist
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "==> Clean complete."

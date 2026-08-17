# VocabCraft Engine V3: Implementation Plan for Curated Open-Source Dataset Integration

- **Design Spec:** [docs/superpowers/specs/2026-08-16-curated-dataset-pipeline-design.md](file:///Users/hoojinguyen/Projects/vocab-craft-engine/docs/superpowers/specs/2026-08-16-curated-dataset-pipeline-design.md)
- **Goal:** Transform raw 1.82 GB Wiktionary dump into a clean, human-curated 35k-50k vocabulary SQLite mobile database (< 50MB) with 100% Vietnamese definitions, 100% IPA, Tatoeba/PhoMT example sentences, DailyDialog conversations, and CLOTH teacher cloze drills.

---

## Task 1: Environment & Dataset Downloader Extensions

- **Files:**
  - `config/settings.py` (add paths for FVDP dictionary, DailyDialog, CLOTH, PhoMT)
  - `scripts/download_raw_data.py` (implement downloaders for FVDP, DailyDialog, CLOTH)
- **Execution Steps:**
  1. Add `FVDP_DICT_PATH`, `DAILYDIALOG_PATH`, `CLOTH_PATH` constants to `config/settings.py`.
  2. Implement `download_fvdp_dict()` in `scripts/download_raw_data.py` fetching the sanitized Hồ Ngọc Đức StarDict/SQLite dictionary.
  3. Implement `download_dailydialog()` fetching DailyDialog JSON from HuggingFace dataset mirror.
  4. Implement `download_cloth_dataset()` fetching the CLOTH dataset for cloze drills.
- **Verification:**
  - Run `python scripts/download_raw_data.py` and verify all raw files exist in `data/raw/`.

---

## Task 2: Schema Refinements & Staging DB Updates

- **Files:**
  - `src/db/schema.py`
  - `src/export/schema.py`
  - `src/db/duckdb_manager.py`
- **Execution Steps:**
  1. Update `dialogue_nodes` table schema: add `text_en TEXT NOT NULL`, `text_vi TEXT`, `audio_path TEXT`.
  2. Update `word_sentences` junction table schema: add `rank INTEGER DEFAULT 1`.
  3. Ensure DuckDB staging initialization applies all table alterations cleanly.
- **Verification:**
  - Run `.venv/bin/pytest tests/ -k test_schema` to confirm DuckDB and SQLite schemas are aligned.

---

## Task 3: Ingestion Parsers for Curated Datasets

- **Files:**
  - [NEW] `src/ingestion/fvdp_parser.py` (Hồ Ngọc Đức dictionary parser)
  - [NEW] `src/ingestion/dailydialog_parser.py` (DailyDialog parser for dialogue trees)
  - [NEW] `src/ingestion/cloth_parser.py` (CLOTH dataset parser for cloze exercises)
  - `src/pipeline/steps/` (corresponding pipeline step wrappers)
- **Execution Steps:**
  1. Build `FVDPParser` to stream-parse the SQLite/StarDict dictionary, extracting `lemma`, `pos`, `definition_en`, `definition_vi`, `example`.
  2. Build `DailyDialogParser` to convert multi-turn conversations into `dialogue_trees` and branching `dialogue_nodes` with full text.
  3. Build `CLOTHParser` to ingest question prompts, answers, and 3 teacher-crafted grammatical distractors into `reflex_drills`.
- **Verification:**
  - Unit test each parser with mock fixtures in `tests/test_ingestion/`.

---

## Task 4: Vocabulary Curation Filter & Global IPA Engine

- **Files:**
  - [NEW] `src/transform/vocabulary_curator.py`
  - [NEW] `src/pipeline/steps/enrich_ipa.py`
  - `src/media/ipa_mapper.py`
- **Execution Steps:**
  1. Implement `VocabularyCurator` filtering headwords to top 35,000 – 50,000 lemmas using `SUBTLEX-US`, `Oxford 5000`, `NGSL`, and `AWL`.
  2. Implement `EnrichIPAStep` to execute `IPAMapper` (CMUdict -> BEEP -> g2p-en) globally over all curated words, ensuring 100% UK and US IPA coverage.
- **Verification:**
  - Run query `SELECT count(*) FROM words WHERE ipa_us IS NULL` -> must return `0`.

---

## Task 5: Sentence Ranking, Capping & Linking

- **Files:**
  - `src/transform/sentence_linker.py`
  - `src/enrichment/sentence_scorer.py`
- **Execution Steps:**
  1. Filter sentence pool from Tatoeba and PhoMT (clean length, proper punctuation, bilingual balance).
  2. Implement scoring heuristic based on readability and sentence clarity.
  3. Link sentences to words with a strict cap of Top 3 (max 5) sentences per word, populating the `rank` field.
- **Verification:**
  - Verify `SELECT max(cnt) FROM (SELECT count(*) as cnt FROM word_sentences GROUP BY word_id)` is `<= 5`.

---

## Task 6: SQLite Mobile Packaging, Optimization & Audit

- **Files:**
  - `src/export/sqlite_exporter.py`
  - `src/export/verifier.py`
  - `src/export/packager.py`
- **Execution Steps:**
  1. Export all tables from DuckDB staging to SQLite `english_dataset.db`.
  2. Build composite indexes, run `VACUUM` and `PRAGMA optimize`.
  3. Run `DatasetVerifier` to enforce quality gates:
     - File size <= 50 MB.
     - Vietnamese definition coverage >= 95%.
     - IPA coverage >= 99%.
     - Zero broken dialogue nodes.
- **Verification:**
  - Verify SQLite file size < 50MB and query latency < 3ms.
  - Run full test suite: `make test`.

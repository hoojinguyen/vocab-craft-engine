# Pipeline Supercharged Speed Design Spec

> **Date:** 2026-08-12  
> **Status:** APPROVED BY USER  
> **Goal:** Optimize end-to-end dataset pipeline execution from >2 hours to under 5 minutes across Stages 1-4.

---

## 1. Overview & Objectives

The goal of this design is to eliminate major Python-loop I/O bottlenecks across the dataset generation pipeline, scaling throughput by 10x-50x using:
1. **DuckDB Vectorized SQL Engine** for ingestion and transformations.
2. **spaCy Multiprocessing Stream (`nlp.pipe`)** for CPU-bound sentence lemmatization.
3. **DuckDB Native SQLite Extension (`ATTACH ... TYPE SQLITE`)** for zero-overhead C++ database exports.

---

## 2. Architecture & Stage Details

```
[Raw Files]
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ Stage 1: Ingest                                       │
│  - Kaikki JSONL via DuckDB `read_json` fast path      │
│  - Corpora (Tatoeba/OPUS) via DuckDB `read_csv_auto`   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Stage 2: Transform                                    │
│  - CEFR Grading: Pure DuckDB SQL UPDATE from SUBTLEX  │
│  - Sentence Lemmatization: spaCy `nlp.pipe(-1)`       │
│  - Inverse Relations & Topic Mapping: Pure SQL        │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Stage 3: Enrich                                       │
│  - Async Batch Translation pool + Translation Cache   │
│  - Fast Parallel Reflex Drill Generation               │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Stage 4: Export                                       │
│  - DuckDB `ATTACH 'english_dataset.db' AS sqlite`     │
│  - Direct vectorized `INSERT INTO sqlite.table`       │
│  - Post-export SQLite PRAGMA & Composite Indexing     │
└───────────────────────────┴────────────────────────────┘
```

---

## 3. Key Component Designs

### 3.1 Stage 1: Native Vectorized Corpora Ingestion
- Replace row-by-row `ParallelCorpusParser` in Python.
- Load parallel corpus files (Tatoeba / OPUS / OpenSubtitles TSV/CSV) directly into `raw_sentences` using DuckDB `read_csv_auto` with SQL regex quality filters.

### 3.2 Stage 2: Vectorized CEFR & Multiprocess Lemmatization
- **CEFR Grading:**
  - Load `SUBTLEX_US.csv` directly into DuckDB `subtlex_staging`.
  - Execute a single SQL `UPDATE raw_words SET frequency_rank = s.rank, cefr_level = CASE ... FROM subtlex_staging s WHERE raw_words.lemma = s.word`. Execution time < 10ms.
- **Sentence Lemmatization (`_link_word_sentences`):**
  - Stream `raw_sentences` in 5,000-sentence batches.
  - Process via spaCy `nlp.pipe(texts, n_process=-1, batch_size=5000)`.
  - Bulk insert `(word_id, sentence_id)` tuples into DuckDB `word_sentence_map`.

### 3.3 Stage 4: DuckDB Native SQLite Attach Export
- Replace Python tuple-by-tuple `SQLiteBulkWriter` (`commit_every=10`).
- Load DuckDB SQLite extension and execute native attached transfers:
  ```sql
  INSTALL sqlite;
  LOAD sqlite;
  ATTACH 'english_dataset.db' AS sqlite_db (TYPE SQLITE);
  
  INSERT INTO sqlite_db.words SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words;
  INSERT INTO sqlite_db.definitions SELECT id, word_id, definition_en, definition_vi, example, source FROM raw_definitions;
  INSERT INTO sqlite_db.sentences SELECT id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source FROM raw_sentences;
  INSERT INTO sqlite_db.phrases SELECT * FROM raw_phrases;
  INSERT INTO sqlite_db.collocations SELECT * FROM collocations;
  INSERT INTO sqlite_db.word_relations SELECT * FROM raw_relations;
  INSERT INTO sqlite_db.word_topics SELECT * FROM word_topics;
  INSERT INTO sqlite_db.reflex_drills SELECT * FROM reflex_drills;
  
  DETACH sqlite_db;
  ```
- Re-open SQLite connection to execute index creation and `PRAGMA foreign_key_check`.

---

## 4. Verification Plan

### Automated Benchmarks & Tests
1. **Stage 2 CEFR Benchmark:** Verify 50,000 words graded in < 50ms.
2. **Stage 2 Lemmatization Benchmark:** Verify 50,000 sentences lemmatized across CPU cores in < 15s.
3. **Stage 4 Export Benchmark:** Verify complete export to SQLite in < 5s.
4. **Data Integrity Check:** Run `PRAGMA foreign_key_check` and parity row counts between DuckDB staging and SQLite target tables.

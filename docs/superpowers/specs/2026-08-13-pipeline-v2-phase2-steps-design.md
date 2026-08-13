# Pipeline V2 Phase 2: Pipeline Steps & Domain Modules Design

## 1. Overview

Phase 2 migrates the 15 legacy sequential SQLite pipeline steps into clean, modular V2 steps targeting DuckDB staging tables. Execution logic is decoupled into 4 domain layers (`src/ingestion/`, `src/transform/`, `src/enrichment/`, `src/export/`), with thin `BaseStep` wrappers in `src/pipeline/steps/` for DAG orchestration.

### Goals
1. Implement high-performance streaming ingestors for Kaikki (orjson), Tatoeba (polars), OPUS (parallel text streaming), and WordNet (NLTK).
2. Build transform engines for sentence linking, MWE/phrase extraction, relation deduplication, and topic mapping.
3. Build hybrid translation engine (`Argos Translate` primary + `Google Translate` fallback + DuckDB cache) for definition and phrase translations.
4. Build enrichment modules for reflex drills, dialogue scenarios, and optional Edge-TTS audio generation.
5. Build export bridges for `english_dataset.db` (SQLite bridge), `core_3000.db` (curated bundle), and `dataset.json` (orjson dump).

---

## 2. Layer Architecture & Modules

```
src/
├── ingestion/
│   ├── base_ingestor.py      # Abstract streaming ingestor base
│   ├── kaikki_ingestor.py    # Fast orjson streaming Wiktionary parser
│   ├── tatoeba_ingestor.py   # Polars CSV scanner for sentences & links
│   ├── opus_ingestor.py      # Parallel sentence streaming parser
│   └── wordnet_ingestor.py   # NLTK WordNet synset & relation parser
├── transform/
│   ├── sentence_linker.py    # Spacy lemmatized word-sentence matcher
│   ├── phrase_extractor.py   # Collocation & MWE extractor (phrases)
│   ├── relation_builder.py   # WordNet + Kaikki relation deduplication
│   └── topic_mapper.py       # Hypernym chain topic categorizer
├── enrichment/
│   ├── translation.py        # Argos (offline) + Google fallback hybrid engine
│   ├── vi_validator.py       # Vietnamese string quality validator
│   ├── reflex_builder.py     # Distractor & reflex drill exercise generator
│   └── scenario_builder.py   # Multi-turn dialogue tree generator
├── export/
│   ├── sqlite_exporter.py    # Zero-copy DuckDB -> SQLite bridge
│   ├── core_selector.py      # Top 3000 frequency & list overlap filter
│   ├── core_enricher.py      # Core 3000 quality gate validator
│   ├── core_exporter.py      # SQLite exporter for core_3000.db
│   └── json_exporter.py      # Fast orjson exporter for dataset.json
└── pipeline/
    └── steps/                # Thin V2 BaseStep wrappers registered with DAG
        ├── schema_init.py
        ├── ingest_kaikki.py
        ├── ingest_tatoeba.py
        ├── ingest_opus.py
        ├── ingest_wordnet.py
        ├── transform_linking.py
        ├── transform_phrases.py
        ├── transform_relations.py
        ├── enrich_translation.py
        ├── enrich_reflex.py
        ├── enrich_scenarios.py
        ├── enrich_audio.py   # optional=True
        ├── export_sqlite.py
        ├── export_core3000.py
        └── export_json.py
```

---

## 3. Detailed Component Specifications

### 3.1 Ingestion Layer

#### `kaikki_ingestor.py`
- Reads `KAIKKI_JSON_PATH` line-by-line using `orjson.loads()`.
- Processes in batches of 5,000 JSON entries.
- Filters entries with `lang == 'English'` and POS in `['noun', 'verb', 'adj', 'adv']`.
- Populates `words` table with `(lemma, pos, ipa_uk, ipa_us, source='kaikki')`.
- Populates `definitions` table with `(word_id, definition_en, example, source='kaikki')`.
- Deduplicates on `(lemma, pos)` using DuckDB `insert_batch` with `ON CONFLICT DO NOTHING`.

#### `tatoeba_ingestor.py`
- Uses `polars.scan_csv` to scan `sentences.csv` and `links.csv`.
- Filters English sentences paired with Vietnamese translations in Tatoeba.
- Inserts valid sentence pairs into `sentences` table with `source='tatoeba'`.

#### `opus_ingestor.py`
- Streams lines from OpenSubtitles and EnViCorpora parallel files (`data.en` / `data.vi`).
- Filters sentences with word count between 4 and 25 words.
- Caps ingestion at `MAX_SENTENCES_PER_CORPUS=500_000` to prevent disk bloat.
- Inserts sentence pairs into `sentences` with `source='opus'` or `source='envicorpora'`.

#### `wordnet_ingestor.py`
- Loads NLTK WordNet synsets.
- Extracts missing lemmas/POS into `words` table with `source='wordnet'`.
- Extracts lexical relations (synonyms, antonyms, hypernyms, hyponyms) into `word_relations` table with `source='wordnet'`.

---

### 3.2 Transform Layer

#### `sentence_linker.py`
- Reads words and sentences from DuckDB.
- Uses SpaCy lemmatization and exact word token matching to build `word_sentences` pairs.
- Ranks sentences by difficulty score based on sentence length and vocabulary level.

#### `phrase_extractor.py`
- Extracts multi-word expressions (MWEs) from sentence corpora and Kaikki phrase entries.
- Categorizes phrases into `phrase_type`: `collocation` (Adj+N, V+N, N+N), `idiom`, `phrasal_verb`, `proverb`.
- Populates `phrases` and `phrase_sentences` tables.

#### `relation_builder.py` & `topic_mapper.py`
- Merges relation pairs from WordNet and Kaikki, avoiding self-references and inverted duplicates (`inverted=1`).
- Traverses WordNet hypernym paths to map vocabulary into top 20 CEFR domain topics (`word_topics`).

---

### 3.3 Enrichment Layer

#### `translation.py` (Hybrid Translation Engine)
- Checks `_translation_cache` in DuckDB first.
- Primary engine: `argostranslate` offline model (`en` -> `vi`). Runs at ~500 items/sec.
- Validates output using `vi_validator.py` (checks character encoding, non-empty, length sanity).
- Fallback engine: `deep-translator` (Google Translate) if Argos is missing, uninstalled, or fails validation.
- Writes translated strings into `definitions.definition_vi` and `phrases.definition_vi`, storing cached items in `_translation_cache`.

#### `reflex_builder.py`
- Generates 3 types of reflex exercises: `cloze` (fill-in-the-blank), `choice` (select correct word), `speed` (fast response).
- Generates distractor options using word relations (synonyms/antonyms) and frequency-matched words.
- Populates `reflex_drills` table.

#### `scenario_builder.py`
- Groups sentences by topic and CEFR level into multi-turn dialogue trees.
- Populates `dialogue_trees` and `dialogue_nodes`.

#### `enrich_audio.py` (Optional Step)
- Uses `edge-tts` to generate standard and fast reflex audio files for words and phrases.
- Marked with `optional = True` in `BaseStep` V2 so it can be enabled or skipped via CLI.

---

### 3.4 Export Layer

#### `sqlite_exporter.py`
- Uses DuckDB `ATTACH 'data/output/english_dataset.db' AS output (TYPE sqlite)` syntax.
- Performs zero-copy bulk table creation from DuckDB staging to SQLite target database.
- Creates indexes on SQLite destination tables (`idx_words_lemma`, `idx_definitions_word`, `idx_sentences_text`, etc.).

#### `core_selector.py` + `core_enricher.py` + `core_exporter.py`
- Filters the top 3,000 words sorted by `SUBTLEX_US` frequency.
- Verifies overlap with `NGSL` and `Oxford 3000` lists.
- Enforces quality gates: must have valid `definition_vi`, `ipa_us`, `cefr_level`, and example sentence.
- Exports curated database to `data/output/core_3000.db`.

#### `json_exporter.py`
- Serializes complete dataset into nested JSON structures using `orjson.dumps()`.
- Exports to `data/output/dataset.json`.

---

## 4. Verification Plan

### Automated Tests
- Ingestion unit tests: `tests/test_ingestion/` (Kaikki, Tatoeba, OPUS, WordNet)
- Transform unit tests: `tests/test_transform/` (Linker, Phrase Extractor, Relations, Topics)
- Enrichment unit tests: `tests/test_enrichment/` (Translation hybrid, Reflex, Scenarios)
- Export unit tests: `tests/test_export/` (SQLite bridge, Core 3000, JSON exporter)
- Full DAG integration test: `tests/test_pipeline/test_integration.py`

### Performance & Quality Verification
- Total pipeline execution time < 1.5 hours.
- `english_dataset.db` SQLite integrity check (`PRAGMA integrity_check`).
- `core_3000.db` 100% quality gate compliance report.

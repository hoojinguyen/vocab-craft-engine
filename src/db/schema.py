"""
DuckDB staging + internal pipeline schema definitions.

Staging tables hold the vocabulary dataset being built.
Internal tables (prefixed with _) hold pipeline state, caches, and checkpoints.
"""

STAGING_TABLES = [
    "words",
    "definitions",
    "sentences",
    "word_sentences",
    "phrases",
    "phrase_sentences",
    "word_relations",
    "word_topics",
    "reflex_drills",
    "dialogue_trees",
    "dialogue_nodes",
]

INTERNAL_TABLES = [
    "_pipeline_meta",
    "_batch_checkpoints",
    "_translation_cache",
    "_ipa_cache",
]

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id             INTEGER PRIMARY KEY,
    lemma          TEXT NOT NULL,
    pos            TEXT NOT NULL,
    ipa_uk         TEXT,
    ipa_us         TEXT,
    frequency_rank INTEGER,
    cefr_level     TEXT,
    source         TEXT,
    UNIQUE(lemma, pos)
);

CREATE TABLE IF NOT EXISTS definitions (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    definition_en  TEXT,
    definition_vi  TEXT,
    example        TEXT,
    source         TEXT,
    UNIQUE(word_id, definition_en)
);

CREATE TABLE IF NOT EXISTS sentences (
    id               INTEGER PRIMARY KEY,
    text_en          TEXT UNIQUE NOT NULL,
    text_vi          TEXT,
    difficulty_score REAL,
    cefr_level       TEXT,
    audio_path       TEXT,
    source           TEXT
);

CREATE TABLE IF NOT EXISTS word_sentences (
    word_id     INTEGER NOT NULL REFERENCES words(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    PRIMARY KEY (word_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS phrases (
    id               INTEGER PRIMARY KEY,
    phrase           TEXT UNIQUE NOT NULL,
    phrase_type      TEXT NOT NULL,
    pos              TEXT,
    cefr_level       TEXT,
    difficulty_score REAL,
    definition_en    TEXT,
    definition_vi    TEXT,
    ipa              TEXT,
    audio_std        TEXT,
    audio_fast       TEXT,
    audio_status     TEXT DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS phrase_sentences (
    phrase_id   INTEGER NOT NULL REFERENCES phrases(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    rank        INTEGER,
    PRIMARY KEY (phrase_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS word_relations (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id),
    relation_type  TEXT NOT NULL,
    target_text    TEXT NOT NULL,
    target_word_id INTEGER REFERENCES words(id),
    inverted       INTEGER NOT NULL DEFAULT 0,
    source         TEXT,
    UNIQUE(word_id, relation_type, target_text)
);

CREATE TABLE IF NOT EXISTS word_topics (
    word_id   INTEGER NOT NULL REFERENCES words(id),
    topic     TEXT NOT NULL,
    raw_topic TEXT,
    UNIQUE(word_id, topic)
);

CREATE TABLE IF NOT EXISTS reflex_drills (
    id               INTEGER PRIMARY KEY,
    sentence_id      INTEGER NOT NULL REFERENCES sentences(id),
    drill_type       TEXT NOT NULL,
    prompt_text      TEXT,
    correct_answer   TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms   INTEGER DEFAULT 2500
);

CREATE TABLE IF NOT EXISTS dialogue_trees (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    topic        TEXT,
    cefr_level   TEXT,
    root_node_id INTEGER
);

CREATE TABLE IF NOT EXISTS dialogue_nodes (
    id             INTEGER PRIMARY KEY,
    tree_id        INTEGER NOT NULL REFERENCES dialogue_trees(id),
    parent_node_id INTEGER REFERENCES dialogue_nodes(id),
    choice_label   TEXT,
    speaker_role   TEXT NOT NULL,
    sentence_id    INTEGER REFERENCES sentences(id)
);
"""

INTERNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS _pipeline_meta (
    step_name     TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    source_hash   TEXT,
    row_count     INTEGER,
    started_at    TIMESTAMP,
    completed_at  TIMESTAMP,
    duration_secs REAL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS _batch_checkpoints (
    step_name       TEXT NOT NULL,
    batch_id        TEXT NOT NULL,
    rows_written    INTEGER,
    checkpoint_data TEXT,
    created_at      TIMESTAMP,
    PRIMARY KEY (step_name, batch_id)
);

CREATE TABLE IF NOT EXISTS _translation_cache (
    source_text TEXT PRIMARY KEY,
    target_text TEXT NOT NULL,
    translator  TEXT NOT NULL,
    quality     REAL,
    created_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS _ipa_cache (
    word   TEXT PRIMARY KEY,
    ipa_us TEXT,
    ipa_uk TEXT,
    source TEXT
);
"""

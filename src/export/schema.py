"""
Target SQLite Production Schema and Covering Index Definitions.

Defines the final standalone SQLite database structure consumed by client and mobile applications.
"""

SQLITE_TABLES = [
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

SQLITE_SCHEMA = """
-- 1. Words Master Table
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

-- 2. Definitions Table
CREATE TABLE IF NOT EXISTS definitions (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    definition_en  TEXT,
    definition_vi  TEXT,
    example        TEXT,
    source         TEXT,
    UNIQUE(word_id, definition_en)
);

-- 3. Parallel Sentences Table
CREATE TABLE IF NOT EXISTS sentences (
    id               INTEGER PRIMARY KEY,
    text_en          TEXT UNIQUE NOT NULL,
    text_vi          TEXT,
    difficulty_score REAL,
    cefr_level       TEXT,
    audio_path       TEXT,
    source           TEXT
);

-- 4. Word-Sentence Link Mapping Table
CREATE TABLE IF NOT EXISTS word_sentences (
    word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, sentence_id)
);

-- 5. Multi-Word Expressions (Phrases / Idioms / Collocations) Table
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

-- 6. Phrase-Sentence Link Mapping Table
CREATE TABLE IF NOT EXISTS phrase_sentences (
    phrase_id   INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    rank        INTEGER DEFAULT 1,
    PRIMARY KEY (phrase_id, sentence_id)
);

-- 7. Lexical Relations Table
CREATE TABLE IF NOT EXISTS word_relations (
    id             INTEGER PRIMARY KEY,
    word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    relation_type  TEXT NOT NULL,
    target_text    TEXT NOT NULL,
    target_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,
    inverted       INTEGER NOT NULL DEFAULT 0,
    source         TEXT,
    UNIQUE(word_id, relation_type, target_text)
);

-- 8. Thematic Topic Tags Table
CREATE TABLE IF NOT EXISTS word_topics (
    word_id   INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    topic     TEXT NOT NULL,
    raw_topic TEXT,
    PRIMARY KEY (word_id, topic)
);

-- 9. Reflex Drill Cards Table
CREATE TABLE IF NOT EXISTS reflex_drills (
    id               INTEGER PRIMARY KEY,
    sentence_id      INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    drill_type       TEXT NOT NULL,
    prompt_text      TEXT,
    correct_answer   TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms   INTEGER DEFAULT 2500
);

-- 10. Dialogue Scenario Trees Table
CREATE TABLE IF NOT EXISTS dialogue_trees (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    topic        TEXT,
    cefr_level   TEXT,
    root_node_id INTEGER
);

-- 11. Dialogue Tree Nodes Table
CREATE TABLE IF NOT EXISTS dialogue_nodes (
    id             INTEGER PRIMARY KEY,
    tree_id        INTEGER NOT NULL REFERENCES dialogue_trees(id) ON DELETE CASCADE,
    parent_node_id INTEGER REFERENCES dialogue_nodes(id) ON DELETE CASCADE,
    choice_label   TEXT,
    speaker_role   TEXT NOT NULL,
    sentence_id    INTEGER REFERENCES sentences(id) ON DELETE SET NULL
);

-- 12. Dataset Metadata Table
CREATE TABLE IF NOT EXISTS dataset_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

SQLITE_INDEXES = """
-- Performance Covering Indexes for Client & Mobile Querying
CREATE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);
CREATE INDEX IF NOT EXISTS idx_words_cefr ON words(cefr_level);
CREATE INDEX IF NOT EXISTS idx_words_freq ON words(frequency_rank);
CREATE INDEX IF NOT EXISTS idx_definitions_word ON definitions(word_id);
CREATE INDEX IF NOT EXISTS idx_sentences_cefr ON sentences(cefr_level);
CREATE INDEX IF NOT EXISTS idx_word_sentences_word ON word_sentences(word_id);
CREATE INDEX IF NOT EXISTS idx_word_sentences_sent ON word_sentences(sentence_id);
CREATE INDEX IF NOT EXISTS idx_phrases_phrase ON phrases(phrase);
CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);
CREATE INDEX IF NOT EXISTS idx_word_relations_word ON word_relations(word_id);
CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);
CREATE INDEX IF NOT EXISTS idx_word_topics_word ON word_topics(word_id);
CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);
CREATE INDEX IF NOT EXISTS idx_reflex_drills_sent ON reflex_drills(sentence_id);
CREATE INDEX IF NOT EXISTS idx_dialogue_nodes_tree ON dialogue_nodes(tree_id);
"""

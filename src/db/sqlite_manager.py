"""Optimized SQLite bulk writer with WAL mode and deferred commits."""

import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

BULK_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = OFF;",
    "PRAGMA cache_size = -20000;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 268435456;",
    "PRAGMA page_size = 4096;",
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma TEXT UNIQUE NOT NULL,
    pos TEXT NOT NULL,
    ipa_uk TEXT,
    ipa_us TEXT,
    frequency_rank INTEGER,
    cefr_level TEXT
);

CREATE TABLE IF NOT EXISTS definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    definition_en TEXT,
    definition_vi TEXT,
    example TEXT,
    source TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE NOT NULL,
    meaning_vi TEXT,
    pos_pattern TEXT,
    cefr_level TEXT
);

CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_en TEXT UNIQUE NOT NULL,
    text_vi TEXT,
    difficulty_score REAL,
    cefr_level TEXT,
    audio_path TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS word_sentence_map (
    word_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    PRIMARY KEY (word_id, sentence_id),
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reflex_drills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id INTEGER NOT NULL,
    drill_type TEXT NOT NULL,
    prompt_text TEXT,
    correct_answer TEXT NOT NULL,
    distractors_json TEXT,
    target_time_ms INTEGER DEFAULT 2500,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dialogue_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    topic TEXT,
    cefr_level TEXT,
    root_node_id INTEGER
);

CREATE TABLE IF NOT EXISTS dialogue_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL,
    parent_node_id INTEGER,
    choice_label TEXT,
    speaker_role TEXT NOT NULL,
    sentence_id INTEGER,
    FOREIGN KEY (tree_id) REFERENCES dialogue_trees (id) ON DELETE CASCADE,
    FOREIGN KEY (parent_node_id) REFERENCES dialogue_nodes (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE NOT NULL,
    phrase_type TEXT NOT NULL,
    pos TEXT,
    cefr_level TEXT,
    difficulty_score REAL,
    definition_en TEXT,
    definition_vi TEXT,
    ipa TEXT,
    audio_std TEXT,
    audio_fast TEXT,
    audio_status TEXT DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS phrase_sentences (
    phrase_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    rank INTEGER,
    PRIMARY KEY (phrase_id, sentence_id),
    FOREIGN KEY (phrase_id) REFERENCES phrases (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS word_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    target_text TEXT NOT NULL,
    target_word_id INTEGER,
    inverted INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    FOREIGN KEY (target_word_id) REFERENCES words (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS word_topics (
    word_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    raw_topic TEXT,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, topic)
);

CREATE TABLE IF NOT EXISTS sentence_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT UNIQUE NOT NULL,
    structure_json TEXT,
    example_en TEXT,
    example_vi TEXT,
    cefr_level TEXT
);
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);
CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);
CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);
CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);
CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);
CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);
CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);
CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);
CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);
CREATE INDEX IF NOT EXISTS idx_definitions_word_id ON definitions(word_id);
"""


class SQLiteBulkWriter:
    """High-performance SQLite writer with WAL, bulk transactions, and mmap."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.execute("PRAGMA foreign_keys = ON;")
            for pragma in BULK_PRAGMAS:
                self.conn.execute(pragma)
            logger.info("SQLite connected (WAL): %s", self.db_path)
        return self.conn

    def init_schema(self):
        self.connect().executescript(SCHEMA_SQL)
        logger.info("SQLite schema initialized.")

    def create_indexes(self):
        self.connect().executescript(INDEX_SQL)
        logger.info("SQLite indexes created.")

    def insert_words(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level) VALUES (:lemma, :pos, :ipa_uk, :ipa_us, :frequency_rank, :cefr_level)",
            rows, commit_every)

    def insert_definitions(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT INTO definitions (word_id, definition_en, definition_vi, example, source) VALUES (:word_id, :definition_en, :definition_vi, :example, :source)",
            rows, commit_every)

    def insert_sentences(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, audio_path, source) VALUES (:text_en, :text_vi, :difficulty_score, :cefr_level, :audio_path, :source)",
            rows, commit_every)

    def insert_collocations(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level) VALUES (:phrase, :meaning_vi, :pos_pattern, :cefr_level)",
            rows, commit_every)

    def insert_word_sentence_map(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO word_sentence_map (word_id, sentence_id) VALUES (:word_id, :sentence_id)",
            rows, commit_every)

    def insert_phrases(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            """INSERT OR IGNORE INTO phrases (phrase, phrase_type, pos, cefr_level, difficulty_score, definition_en, definition_vi, ipa, audio_std, audio_fast, audio_status)
            VALUES (:phrase, :phrase_type, :pos, :cefr_level, :difficulty_score, :definition_en, :definition_vi, :ipa, :audio_std, :audio_fast, :audio_status)""",
            rows, commit_every)

    def insert_word_relations(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO word_relations (word_id, relation_type, target_text, target_word_id, inverted, source) VALUES (:word_id, :relation_type, :target_text, :target_word_id, :inverted, :source)",
            rows, commit_every)

    def insert_word_topics(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic) VALUES (:word_id, :topic, :raw_topic)",
            rows, commit_every)

    def insert_reflex_drills(self, rows: List[Dict[str, Any]], commit_every: int = 10):
        self._batch_insert(
            "INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms) VALUES (:sentence_id, :drill_type, :prompt_text, :correct_answer, :distractors_json, :target_time_ms)",
            rows, commit_every)

    def insert_dialogue_trees(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (:title, :topic, :cefr_level)",
            rows, commit_every)

    def insert_dialogue_nodes(self, rows: List[Dict[str, Any]], commit_every: int = 5):
        self._batch_insert(
            "INSERT INTO dialogue_nodes (tree_id, parent_node_id, sentence_id, speaker_role, choice_label) VALUES (:tree_id, :parent_node_id, :sentence_id, :speaker_role, :choice_label)",
            rows, commit_every)

    def _batch_insert(self, sql: str, rows: List[Dict[str, Any]], commit_every: int):
        if not rows:
            return
        conn = self.conn
        cursor = conn.cursor()
        batches_since_commit = 0
        for i in range(0, len(rows), 5000):
            batch = rows[i:i + 5000]
            cursor.executemany(sql, batch)
            batches_since_commit += 1
            if batches_since_commit >= commit_every:
                conn.commit()
                batches_since_commit = 0
        if batches_since_commit > 0:
            conn.commit()

    def optimize(self):
        conn = self.conn
        conn.execute("ANALYZE;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

"""DuckDB staging manager for parallel ingest and bulk transforms."""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import duckdb

logger = logging.getLogger(__name__)


STAGING_PRAGMAS = [
    "PRAGMA threads = 4",
    "PRAGMA memory_limit = '8GB'",
    "PRAGMA enable_object_cache",
    "PRAGMA enable_progress_bar",
    "PRAGMA preserve_insertion_order = false",
]

SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS raw_words_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_sentences_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_phrases_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS raw_relations_id_seq START 1;

CREATE TABLE IF NOT EXISTS raw_words (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    lemma VARCHAR UNIQUE NOT NULL,
    pos VARCHAR NOT NULL,
    ipa_uk VARCHAR,
    ipa_us VARCHAR,
    frequency_rank INTEGER,
    cefr_level VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_definitions (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    lemma VARCHAR NOT NULL,
    definition_en VARCHAR,
    definition_vi VARCHAR,
    example VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_phrases (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_phrases_id_seq'),
    phrase VARCHAR UNIQUE NOT NULL,
    phrase_type VARCHAR NOT NULL,
    pos VARCHAR,
    cefr_level VARCHAR,
    difficulty_score DOUBLE,
    definition_en VARCHAR,
    definition_vi VARCHAR,
    ipa VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_relations (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_relations_id_seq'),
    lemma VARCHAR NOT NULL,
    relation_type VARCHAR NOT NULL,
    target_text VARCHAR NOT NULL,
    target_word_id INTEGER,
    inverted INTEGER DEFAULT 0,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_topics (
    lemma VARCHAR NOT NULL,
    topic VARCHAR NOT NULL,
    raw_topic VARCHAR,
    PRIMARY KEY (lemma, topic)
);

CREATE TABLE IF NOT EXISTS raw_sentences (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_sentences_id_seq'),
    text_en VARCHAR UNIQUE NOT NULL,
    text_vi VARCHAR,
    difficulty_score DOUBLE,
    cefr_level VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS collocations (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    phrase VARCHAR UNIQUE NOT NULL,
    meaning_vi VARCHAR,
    pos_pattern VARCHAR,
    cefr_level VARCHAR
);

CREATE TABLE IF NOT EXISTS word_sentence_map (
    word_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    PRIMARY KEY (word_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS reflex_drills (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    sentence_id INTEGER NOT NULL,
    drill_type VARCHAR NOT NULL,
    prompt_text VARCHAR,
    correct_answer VARCHAR NOT NULL,
    distractors_json VARCHAR,
    target_time_ms INTEGER DEFAULT 2500
);

CREATE TABLE IF NOT EXISTS dialogue_trees (
    id INTEGER PRIMARY KEY DEFAULT nextval('raw_words_id_seq'),
    title VARCHAR NOT NULL,
    topic VARCHAR,
    cefr_level VARCHAR
);
"""


class DuckDBManager:
    """Manages DuckDB staging database for ETL pipeline."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self.conn is None:
            self.conn = duckdb.connect(str(self.db_path))
            for pragma in STAGING_PRAGMAS:
                self.conn.execute(pragma)
            logger.info("DuckDB connected: %s", self.db_path)
        return self.conn

    def init_schema(self):
        conn = self.connect()
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        logger.info("DuckDB schema initialized.")

    def insert_rows(self, table: str, rows: List[Dict[str, Any]], batch_size: int = 10_000):
        if not rows:
            return
        conn = self.connect()
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            columns = list(batch[0].keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join(columns)
            sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"
            values = [tuple(row[c] for c in columns) for row in batch]
            conn.executemany(sql, values)
        conn.commit()

    def query(self, sql: str, params: tuple = ()):
        return self.connect().execute(sql, params)

    def execute(self, sql: str, params: tuple = ()):
        self.connect().execute(sql, params)

    def export_to_sqlite(self, table: str, sqlite_path: Path, table_name: Optional[str] = None):
        target = table_name or table
        conn = self.connect()
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(f"ATTACH '{sqlite_path}' AS sq (TYPE sqlite)")
        conn.execute(f"CREATE TABLE IF NOT EXISTS sq.{target} AS SELECT * FROM {table} WHERE 0=1")
        conn.execute(f"INSERT INTO sq.{target} SELECT * FROM {table}")
        conn.execute("DETACH sq")
        conn.commit()
        logger.info("Exported %s -> sqlite:%s", table, target)

    def row_count(self, table: str) -> int:
        return self.connect().execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

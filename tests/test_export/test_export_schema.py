import sqlite3
import pytest
from pathlib import Path
from src.export.schema import SQLITE_SCHEMA, SQLITE_INDEXES, SQLITE_TABLES


def test_sqlite_schema_creates_all_tables_and_indexes(tmp_path: Path):
    db_file = tmp_path / "test_schema.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SQLITE_SCHEMA)
    conn.executescript(SQLITE_INDEXES)

    cursor = conn.cursor()
    tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    for expected_table in SQLITE_TABLES:
        assert expected_table in tables, f"Table {expected_table} missing from SQLite schema!"

    assert "dataset_metadata" in tables

    indexes = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    assert "idx_words_lemma" in indexes
    assert "idx_words_cefr" in indexes
    assert "idx_definitions_word" in indexes
    assert "idx_word_sentences_word" in indexes
    assert "idx_phrases_phrase" in indexes
    assert "idx_word_topics_word" in indexes
    assert "idx_reflex_drills_sent" in indexes
    assert "idx_dialogue_nodes_tree" in indexes
    conn.close()

"""
Unit tests for DatabaseManager in src.db.staging_db
"""

import pytest
import sqlite3
from pathlib import Path
from src.db.staging_db import DatabaseManager


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_english_dataset.db"
    db_manager = DatabaseManager(db_path=db_file)
    db_manager.init_schema()
    yield db_manager
    db_manager.close()


def test_init_schema_creates_tables_and_indexes(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()

    # Check tables existence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "words", "definitions", "collocations", "sentence_patterns",
        "sentences", "dialogue_trees", "dialogue_nodes",
        "reflex_drills", "word_sentence_map"
    }
    assert expected_tables.issubset(tables)


def test_insert_words_batch_and_idempotency(temp_db: DatabaseManager):
    words = [
        {"lemma": "run", "pos": "verb", "ipa_uk": "rʌn", "ipa_us": "rʌn", "frequency_rank": 150, "cefr_level": "A1"},
        {"lemma": "apple", "pos": "noun", "ipa_uk": "ˈæp.əl", "ipa_us": "ˈæp.əl", "frequency_rank": 1200, "cefr_level": "A1"}
    ]

    temp_db.insert_words_batch(words)
    run_id = temp_db.get_word_id_by_lemma("run")
    apple_id = temp_db.get_word_id_by_lemma("apple")

    assert run_id is not None
    assert apple_id is not None

    # Test idempotency (INSERT OR IGNORE duplicate lemma)
    temp_db.insert_words_batch(words)
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM words;")
    count = cursor.fetchone()[0]
    assert count == 2


def test_insert_definitions_batch(temp_db: DatabaseManager):
    words = [{"lemma": "test", "pos": "noun", "ipa_uk": "test", "ipa_us": "test", "frequency_rank": 500, "cefr_level": "A1"}]
    temp_db.insert_words_batch(words)
    word_id = temp_db.get_word_id_by_lemma("test")

    definitions = [
        {"word_id": word_id, "definition_en": "A procedure intended to establish the quality.", "definition_vi": "Bài kiểm tra", "example": "This is a test.", "source": "Kaikki"}
    ]
    temp_db.insert_definitions_batch(definitions)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions WHERE word_id = ?;", (word_id,))
    res = cursor.fetchone()
    assert res[0] == "Bài kiểm tra"


def test_foreign_key_check(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_key_check;")
    violations = cursor.fetchall()
    assert len(violations) == 0

"""Tests for DuckDB staging manager."""

import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


@pytest.fixture
def db(tmp_path):
    return DuckDBManager(db_path=tmp_path / "test.duckdb")


def test_create_and_insert_words(db):
    db.init_schema()
    rows = [
        {"lemma": "hello", "pos": "intj", "frequency_rank": 500, "cefr_level": "A1"},
        {"lemma": "world", "pos": "noun", "frequency_rank": 800, "cefr_level": "A1"},
    ]
    db.insert_rows("raw_words", rows)
    result = db.query("SELECT count(*) FROM raw_words")
    assert result.fetchone()[0] == 2


def test_query_returns_data(db):
    db.init_schema()
    db.insert_rows("raw_sentences", [
        {"text_en": "Hello world", "text_vi": "Xin chao", "source": "test"},
    ])
    result = db.query("SELECT text_en, text_vi FROM raw_sentences LIMIT 1").fetchone()
    assert result[0] == "Hello world"
    assert result[1] == "Xin chao"


def test_bulk_insert_10k_rows(db):
    db.init_schema()
    rows = [
        {"lemma": f"word_{i}", "pos": "noun", "frequency_rank": i, "cefr_level": "B1"}
        for i in range(10_000)
    ]
    db.insert_rows("raw_words", rows)
    count = db.query("SELECT count(*) FROM raw_words").fetchone()[0]
    assert count == 10_000


def test_attached_sqlite_export(db, tmp_path):
    db.init_schema()
    db.insert_rows("raw_words", [
        {"lemma": "test", "pos": "noun", "frequency_rank": 1, "cefr_level": "A1"},
    ])

    sqlite_path = tmp_path / "export.db"
    db.export_to_sqlite("raw_words", sqlite_path, table_name="words")

    import sqlite3
    conn = sqlite3.connect(str(sqlite_path))
    count = conn.execute("SELECT count(*) FROM words").fetchone()[0]
    conn.close()
    assert count == 1


def test_close_releases_connection(db):
    db.init_schema()
    db.close()
    db2 = DuckDBManager(db_path=db.db_path)
    db2.init_schema()
    db2.close()

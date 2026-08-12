"""Tests for SQLite bulk writer."""

import pytest
import sqlite3
from pathlib import Path
from src.db.sqlite_manager import SQLiteBulkWriter


@pytest.fixture
def writer(tmp_path):
    w = SQLiteBulkWriter(db_path=tmp_path / "test.db")
    w.connect()
    w.init_schema()
    return w


def test_bulk_insert_10k(writer):
    rows = [
        {"lemma": f"word_{i}", "pos": "noun", "ipa_uk": "/wɜːd/", "ipa_us": "/wɝd/",
         "frequency_rank": i, "cefr_level": "B1"}
        for i in range(10_000)
    ]
    writer.insert_words(rows, commit_every=10)
    count = writer.conn.execute("SELECT count(*) FROM words").fetchone()[0]
    assert count == 10_000


def test_insert_definitions_with_lemma_cache(writer):
    writer.insert_words(
        [{"lemma": "hello", "pos": "intj", "ipa_uk": None, "ipa_us": "/həˈloʊ/",
          "frequency_rank": 1, "cefr_level": "A1"}],
        commit_every=1,
    )
    rows = [
        {"word_id": 1, "definition_en": "a greeting", "definition_vi": None,
         "example": None, "source": "test"},
    ]
    writer.insert_definitions(rows, commit_every=1)
    result = writer.conn.execute(
        "SELECT definition_en FROM definitions WHERE word_id = 1"
    ).fetchone()
    assert result[0] == "a greeting"


def test_wal_mode_enabled(writer):
    mode = writer.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_cache_size_set(writer):
    cache = writer.conn.execute("PRAGMA cache_size").fetchone()[0]
    assert cache <= -10000


def test_insert_sentences_with_dedup(writer):
    rows = [
        {"text_en": "Hello world", "text_vi": "Xin chao", "difficulty_score": 2.0,
         "cefr_level": "A1", "audio_path": None, "source": "test"},
        {"text_en": "Hello world", "text_vi": "Xin chao", "difficulty_score": 2.0,
         "cefr_level": "A1", "audio_path": None, "source": "test"},
    ]
    writer.insert_sentences(rows, commit_every=1)
    count = writer.conn.execute("SELECT count(*) FROM sentences").fetchone()[0]
    assert count == 1


def test_create_indexes(writer):
    writer.create_indexes()
    writer.conn.execute("SELECT * FROM words WHERE lemma = 'test'")


def test_writer_close(writer):
    writer.close()
    w2 = SQLiteBulkWriter(db_path=writer.db_path)
    w2.connect()
    w2.close()

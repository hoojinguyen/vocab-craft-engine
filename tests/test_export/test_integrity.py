import sqlite3
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SQLiteExporter


@pytest.fixture
def exported_sqlite(tmp_path):
    staging_path = tmp_path / "staging.duckdb"
    sqlite_path = tmp_path / "english_dataset.db"

    mgr = DuckDBManager(db_path=staging_path)
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "apple", "pos": "noun"}])
    mgr.insert_batch("definitions", [{"word_id": 1, "definition_en": "a fruit"}])

    exporter = SQLiteExporter()
    exporter.export(mgr, sqlite_path)
    mgr.close()
    return sqlite_path


def test_sqlite_journal_mode(exported_sqlite):
    conn = sqlite3.connect(exported_sqlite)
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_sqlite_words_and_defs_integrity(exported_sqlite):
    conn = sqlite3.connect(exported_sqlite)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM words")
    w_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM definitions")
    d_count = cur.fetchone()[0]

    assert w_count == 1
    assert d_count == 1
    conn.close()

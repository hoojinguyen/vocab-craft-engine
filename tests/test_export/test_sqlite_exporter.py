import sqlite3
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SQLiteExporter
from src.pipeline.steps.export_sqlite import ExportSQLiteStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    yield mgr, tmp_path
    mgr.close()


def test_sqlite_exporter(db_mgr):
    staging_mgr, tmp_path = db_mgr
    target_sqlite = tmp_path / "english_dataset.db"

    exporter = SQLiteExporter()
    exported = exporter.export(staging_mgr, target_sqlite)

    assert exported > 0
    assert target_sqlite.exists()

    conn = sqlite3.connect(target_sqlite)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM words")
    row = cursor.fetchone()
    assert row[0] == 1
    conn.close()

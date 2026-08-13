import pytest
from src.db.duckdb_manager import DuckDBManager


def test_duckdb_manager_pragmas(tmp_path):
    db_path = tmp_path / "test_pragmas.duckdb"
    mgr = DuckDBManager(db_path=db_path)
    conn = mgr.get_connection()

    threads = conn.execute("SELECT current_setting('threads')").fetchone()[0]
    memory_limit = conn.execute("SELECT current_setting('max_memory')").fetchone()[0]

    assert int(threads) <= 4
    assert memory_limit is not None
    mgr.close()

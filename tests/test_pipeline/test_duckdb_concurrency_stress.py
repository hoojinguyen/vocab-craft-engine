import concurrent.futures
from pathlib import Path
import pyarrow as pa
import pytest
from src.db.duckdb_manager import DuckDBManager


def test_duckdb_manager_concurrent_reads_and_writes(tmp_path: Path):
    db_path = tmp_path / "concurrent_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    def worker_insert(worker_id: int):
        words = [{"lemma": f"word_{worker_id}_{i}", "pos": "noun", "source": f"worker_{worker_id}"} for i in range(100)]
        db_mgr.insert_batch_fast("words", words)
        rows = db_mgr.fetch_all("SELECT count(*) FROM words WHERE source = ?", [f"worker_{worker_id}"])
        assert rows[0][0] == 100

    def worker_read():
        for _ in range(50):
            count = db_mgr.count_rows("words")
            assert count >= 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        write_futures = [executor.submit(worker_insert, i) for i in range(8)]
        read_futures = [executor.submit(worker_read) for _ in range(4)]
        for f in concurrent.futures.as_completed(write_futures + read_futures):
            f.result()

    assert db_mgr.count_rows("words") == 800
    db_mgr.close()


def test_duckdb_manager_lock_property(tmp_path: Path):
    db_path = tmp_path / "lock_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # Verify lock attribute is an RLock and can be acquired directly
    with db_mgr.lock:
        db_mgr.execute("CREATE TABLE test_lock (id INTEGER, val TEXT)")
        db_mgr.execute("INSERT INTO test_lock VALUES (?, ?)", [1, "alpha"])

    res = db_mgr.fetch_one("SELECT val FROM test_lock WHERE id = ?", [1])
    assert res is not None
    assert res[0] == "alpha"
    db_mgr.close()


def test_duckdb_manager_execute_and_fetch_methods(tmp_path: Path):
    db_path = tmp_path / "methods_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # execute without params
    db_mgr.execute("CREATE TABLE kv_test (k TEXT PRIMARY KEY, v INTEGER)")

    # execute with params
    db_mgr.execute("INSERT INTO kv_test VALUES (?, ?)", ["a", 10])
    db_mgr.execute("INSERT INTO kv_test VALUES (?, ?)", ["b", 20])

    # fetch_one existing
    one = db_mgr.fetch_one("SELECT v FROM kv_test WHERE k = ?", ["a"])
    assert one == (10,)

    # fetch_one missing
    missing = db_mgr.fetch_one("SELECT v FROM kv_test WHERE k = ?", ["nonexistent"])
    assert missing is None

    # fetch_all
    all_rows = db_mgr.fetch_all("SELECT k, v FROM kv_test ORDER BY v ASC")
    assert all_rows == [("a", 10), ("b", 20)]

    # fetch_all with params
    filtered = db_mgr.fetch_all("SELECT k, v FROM kv_test WHERE v > ?", [15])
    assert filtered == [("b", 20)]

    db_mgr.close()


def test_duckdb_manager_concurrent_arrow_inserts(tmp_path: Path):
    db_path = tmp_path / "arrow_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    def worker_arrow_insert(worker_id: int):
        table = pa.Table.from_pydict({
            "lemma": [f"arrow_word_{worker_id}_{i}" for i in range(50)],
            "pos": ["verb"] * 50,
            "source": [f"arrow_worker_{worker_id}"] * 50,
        })
        count = db_mgr.insert_arrow("words", table)
        assert count == 50

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker_arrow_insert, i) for i in range(6)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert db_mgr.count_rows("words") == 300
    db_mgr.close()

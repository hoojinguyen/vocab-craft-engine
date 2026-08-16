from pathlib import Path
from threading import Thread

import pytest

from src.learning.schema import GRAPH_TABLES, MIGRATIONS
from src.learning.store import LearningGraphStore


def _source_asset(asset_id: str) -> tuple[object, ...]:
    return (
        asset_id,
        "Test source",
        "https://example.test/source",
        "2026-01",
        "a" * 64,
        "",
        "https://example.test/license",
        "",
        False,
        "candidate",
    )


def test_initialize_is_idempotent_and_creates_graph_schema(tmp_path: Path):
    store = LearningGraphStore(tmp_path / "nested" / "graph.duckdb")

    store.initialize()
    store.initialize()

    assert store.fetch_value("SELECT count(*) FROM graph_schema_migrations") == len(
        MIGRATIONS
    )
    tables = {row[0] for row in store.connection().execute("SHOW TABLES").fetchall()}
    assert set(GRAPH_TABLES).issubset(tables)


def test_initialize_rejects_newer_database_version(tmp_path: Path):
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    connection = store.connection()
    connection.execute(
        "CREATE TABLE graph_schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp)"
    )
    connection.execute(
        "INSERT INTO graph_schema_migrations VALUES (99, current_timestamp)"
    )

    with pytest.raises(RuntimeError, match="newer than this engine"):
        store.initialize()


def test_transactions_commit_and_roll_back(tmp_path: Path):
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    insert_sql = """
        INSERT INTO source_assets (
            asset_id, title, locator, asset_version, sha256, license_id,
            license_url, attribution, redistribution_allowed, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    with store.transaction() as connection:
        connection.execute(insert_sql, _source_asset("committed-source"))

    with (
        pytest.raises(LookupError, match="sentinel"),
        store.transaction() as connection,
    ):
        connection.execute(insert_sql, _source_asset("rolled-back-source"))
        raise LookupError("sentinel")

    assert (
        store.fetch_value(
            "SELECT count(*) FROM source_assets WHERE asset_id = ?",
            ["committed-source"],
        )
        == 1
    )
    assert (
        store.fetch_value(
            "SELECT count(*) FROM source_assets WHERE asset_id = ?",
            ["rolled-back-source"],
        )
        == 0
    )


def test_transaction_lock_allows_nested_store_helpers(tmp_path: Path):
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    errors: list[BaseException] = []

    def use_store_inside_transaction() -> None:
        try:
            with store.transaction():
                assert store.fetch_value("SELECT 42") == 42
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = Thread(target=use_store_inside_transaction, daemon=True)
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert errors == []


def test_fetch_value_and_close_allow_reopening(tmp_path: Path):
    db_path = tmp_path / "graph.duckdb"
    store = LearningGraphStore(db_path)
    store.initialize()
    assert store.fetch_value("SELECT ?", ["scalar"]) == "scalar"
    assert (
        store.fetch_value(
            "SELECT asset_id FROM source_assets WHERE asset_id = ?", ["missing"]
        )
        is None
    )

    store.close()
    assert store.fetch_value("SELECT count(*) FROM graph_schema_migrations") == len(
        MIGRATIONS
    )

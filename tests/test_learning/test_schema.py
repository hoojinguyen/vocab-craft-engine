import duckdb
import pytest

from src.learning.schema import GRAPH_TABLES, MIGRATIONS


def test_initial_graph_migration_creates_every_graph_table():
    conn = duckdb.connect(":memory:")
    for _, sql in MIGRATIONS:
        conn.execute(sql)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert set(GRAPH_TABLES).issubset(tables)
    assert "graph_schema_migrations" in tables


def test_approved_source_assets_require_rights_evidence():
    conn = duckdb.connect(":memory:")
    for _, sql in MIGRATIONS:
        conn.execute(sql)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO source_assets (
                asset_id, title, locator, asset_version, sha256, license_id,
                license_url, attribution, redistribution_allowed, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "bad-source",
                "Bad source",
                "https://example.test/source",
                "2026-01",
                "a" * 64,
                "",
                "https://example.test/license",
                "",
                False,
                "approved",
            ],
        )

    conn.execute(
        """
        INSERT INTO source_assets (
            asset_id, title, locator, asset_version, sha256, license_id,
            license_url, attribution, redistribution_allowed, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "good-source",
            "Good source",
            "https://example.test/source",
            "2026-01",
            "b" * 64,
            "CC-BY-4.0",
            "https://example.test/license",
            "Test author",
            True,
            "approved",
        ],
    )

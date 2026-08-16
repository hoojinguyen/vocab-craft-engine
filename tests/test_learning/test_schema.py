import duckdb
import pytest

from src.learning.schema import (
    GRAPH_TABLES,
    MIGRATION_001,
    apply_migrations,
)


def test_initial_graph_migration_creates_every_graph_table():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert set(GRAPH_TABLES).issubset(tables)
    assert "graph_schema_migrations" in tables


def test_approved_source_assets_require_rights_evidence():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)

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


def test_migration_v2_quarantines_invalid_approved_sources_and_is_idempotent():
    conn = duckdb.connect(":memory:")
    conn.execute(MIGRATION_001)
    conn.execute(
        """
        INSERT INTO source_assets (
            asset_id, title, locator, asset_version, sha256, license_id,
            license_url, attribution, redistribution_allowed, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "legacy-source",
            "Legacy source",
            "https://example.test/source",
            "2026-01",
            "c" * 64,
            "",
            "https://example.test/license",
            "",
            False,
            "approved",
        ],
    )

    apply_migrations(conn)
    assert conn.execute(
        "SELECT validation_status FROM source_assets WHERE asset_id = 'legacy-source'"
    ).fetchone() == ("quarantined",)
    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,)]

    apply_migrations(conn)
    assert conn.execute(
        "SELECT validation_status FROM source_assets WHERE asset_id = 'legacy-source'"
    ).fetchone() == ("quarantined",)


def test_migration_runner_rejects_newer_database_versions():
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE graph_schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp)"
    )
    conn.execute("INSERT INTO graph_schema_migrations VALUES (99, current_timestamp)")

    with pytest.raises(ValueError, match="newer"):
        apply_migrations(conn)


def test_migration_v2_rejects_mismatched_legacy_review_and_rolls_back():
    conn = duckdb.connect(":memory:")
    conn.execute(MIGRATION_001)
    conn.execute(
        """
        INSERT INTO source_assets (
            asset_id, title, locator, asset_version, sha256, license_id,
            license_url, attribution, redistribution_allowed, validation_status
        ) VALUES ('legacy-source', 'Legacy source', 'https://example.test/source',
                  '2026-01', ?, 'CC-BY-4.0', 'https://example.test/license',
                  'Test author', TRUE, 'candidate')
        """,
        ["d" * 64],
    )
    conn.execute(
        """
        INSERT INTO raw_reference_records VALUES
        ('raw-1', 'legacy-source', 'external-1', 'word', '{}', ?, 'run-1', current_timestamp)
        """,
        ["e" * 64],
    )
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-a', 'raw-1', 'objective', '{}', '{}', 1.0, 'candidate', current_timestamp),
        ('candidate-b', 'raw-1', 'objective', '{}', '{}', 1.0, 'candidate', current_timestamp)
        """)
    conn.execute(
        "INSERT INTO canonical_content VALUES ('content-1', 'objective.greet', 'objective', current_timestamp)"
    )
    conn.execute(
        """
        INSERT INTO content_revisions VALUES
        ('revision-1', 'content-1', 1, '{}', ?, 'candidate', 'candidate-a', current_timestamp)
        """,
        ["f" * 64],
    )
    conn.execute("""
        INSERT INTO content_reviews VALUES
        ('review-1', 'candidate-b', 'revision-1', 'approved', 'reviewer', 'mismatch', current_timestamp)
        """)

    with pytest.raises(RuntimeError, match="candidate"):
        apply_migrations(conn)

    assert conn.execute("SHOW TABLES").fetchall()
    assert conn.execute("SELECT version FROM graph_schema_migrations").fetchall() == []


def test_migration_v2_enforces_composite_review_foreign_key():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO source_assets VALUES
        ('source-1', 'Source', 'https://example.test/source', '2026-01', ?,
         'CC-BY-4.0', 'https://example.test/license', 'Test author', TRUE,
         'candidate', current_timestamp)
        """,
        ["1" * 64],
    )
    conn.execute(
        """
        INSERT INTO raw_reference_records VALUES
        ('raw-1', 'source-1', 'external-1', 'word', '{}', ?, 'run-1', current_timestamp)
        """,
        ["2" * 64],
    )
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-a', 'raw-1', 'objective', '{}', '{}', 1.0, 'candidate', current_timestamp),
        ('candidate-b', 'raw-1', 'objective', '{}', '{}', 1.0, 'candidate', current_timestamp)
        """)
    conn.execute(
        "INSERT INTO canonical_content VALUES ('content-1', 'objective.greet', 'objective', current_timestamp)"
    )
    conn.execute(
        """
        INSERT INTO content_revisions VALUES
        ('revision-1', 'content-1', 1, '{}', ?, 'candidate', 'candidate-a', current_timestamp)
        """,
        ["3" * 64],
    )

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            "INSERT INTO content_reviews VALUES (?, ?, ?, ?, ?, ?, current_timestamp)",
            [
                "review-bad",
                "candidate-b",
                "revision-1",
                "approved",
                "reviewer",
                "wrong candidate",
            ],
        )

    conn.execute(
        "INSERT INTO content_reviews VALUES (?, ?, NULL, ?, ?, ?, current_timestamp)",
        ["review-null", "candidate-b", "rejected", "reviewer", "no revision"],
    )

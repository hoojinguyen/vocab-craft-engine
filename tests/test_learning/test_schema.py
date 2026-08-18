import json
from pathlib import Path

import duckdb
import pytest

from src.learning import schema
from src.learning.repository import ContentRepository
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


def test_migration_v3_creates_validation_tables_and_validated_candidate_state():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)

    assert {"source_snapshots", "validation_runs", "candidate_gate_results"}.issubset(
        {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    )
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        [
            "fixture-source",
            "Fixture",
            "https://example.test",
            "1",
            "a" * 64,
            "LicenseRef-Test",
            "https://example.test/license",
            "Fixture",
            True,
            "approved",
        ],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "fixture-source", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute(
        "INSERT INTO content_candidates VALUES (?, ?, ?, ?, ?, ?, 'validated', current_timestamp)",
        ["candidate-1", "raw-1", "sense", "{}", "{}", 1.0],
    )

    assert conn.execute(
        "SELECT state FROM content_candidates WHERE candidate_id = 'candidate-1'"
    ).fetchone() == ("validated",)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO content_candidates
                (candidate_id, raw_record_id, content_type, normalized_payload_json,
                 evidence_json, confidence, state)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ["candidate-2", "raw-1", "sense", "{}", "{}", 0.5, "candidate"],
        )


def test_migration_v3_preserves_the_existing_candidate_graph(monkeypatch):
    conn = duckdb.connect(":memory:")
    all_migrations = schema.MIGRATIONS
    v2_migrations = [migration for migration in all_migrations if migration[0] < 3]
    assert len(v2_migrations) == 2
    assert any(version == 3 for version, _ in all_migrations)

    monkeypatch.setattr(schema, "MIGRATIONS", v2_migrations)
    schema.apply_migrations(conn)
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        [
            "legacy-source",
            "Legacy",
            "https://example.test",
            "1",
            "a" * 64,
            "LicenseRef-Test",
            "https://example.test/license",
            "Fixture",
            True,
            "approved",
        ],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "legacy-source", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute(
        "INSERT INTO content_candidates VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["candidate-1", "raw-1", "sense", "{}", "{}", 1.0, "candidate"],
    )
    conn.execute(
        "INSERT INTO canonical_content VALUES (?, ?, ?, current_timestamp)",
        ["content-1", "sense.fixture", "sense"],
    )
    conn.execute(
        "INSERT INTO content_revisions VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["revision-1", "content-1", 1, "{}", "c" * 64, "candidate", "candidate-1"],
    )
    conn.execute(
        "INSERT INTO content_reviews VALUES (?, ?, ?, ?, ?, ?, current_timestamp)",
        ["review-1", "candidate-1", "revision-1", "approved", "reviewer", "legacy"],
    )
    conn.execute(
        "INSERT INTO content_edges VALUES (?, ?, ?, ?, ?)",
        ["edge-1", "revision-1", "revision-1", "supports", "{}"],
    )

    monkeypatch.setattr(schema, "MIGRATIONS", all_migrations)
    schema.apply_migrations(conn)

    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)]
    assert {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "source_assets",
            "raw_reference_records",
            "content_candidates",
            "canonical_content",
            "content_revisions",
            "content_reviews",
            "content_edges",
        )
    } == {
        "source_assets": 1,
        "raw_reference_records": 1,
        "content_candidates": 1,
        "canonical_content": 1,
        "content_revisions": 1,
        "content_reviews": 1,
        "content_edges": 1,
    }


def test_migration_v4_merges_duplicate_candidates_and_repoints_dependents(monkeypatch):
    conn = duckdb.connect(":memory:")
    all_migrations = schema.MIGRATIONS
    v3_migrations = [migration for migration in all_migrations if migration[0] <= 3]
    monkeypatch.setattr(schema, "MIGRATIONS", v3_migrations)
    schema.apply_migrations(conn)
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        [
            "legacy-source",
            "Legacy",
            "https://example.test",
            "1",
            "a" * 64,
            "CC-BY-4.0",
            "https://example.test/license",
            "Fixture",
            True,
            "approved",
        ],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "legacy-source", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-b', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 0.9, 'validated', current_timestamp),
        ('candidate-a', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 1.0, 'validated', current_timestamp)
        """)
    conn.execute(
        "INSERT INTO canonical_content VALUES (?, ?, ?, current_timestamp)",
        ["content-1", "sense.book", "sense"],
    )
    conn.execute(
        """
        INSERT INTO content_revisions VALUES
        ('revision-b', 'content-1', 1, '{"stable_key":"sense.book"}', ?, 'candidate', 'candidate-b', current_timestamp),
        ('revision-a', 'content-1', 2, '{"stable_key":"sense.book"}', ?, 'candidate', 'candidate-a', current_timestamp)
        """,
        ["c" * 64, "d" * 64],
    )
    conn.execute("""
        INSERT INTO content_reviews VALUES
        ('review-b', 'candidate-b', 'revision-b', 'approved', 'reviewer', 'legacy', current_timestamp),
        ('review-a', 'candidate-a', 'revision-a', 'approved', 'reviewer', 'legacy', current_timestamp)
        """)
    conn.execute(
        """
        INSERT INTO source_snapshots VALUES
        ('snapshot-1', 'legacy-source', '/tmp/source.json', current_timestamp, ?, current_timestamp)
        """,
        ["e" * 64],
    )
    conn.execute("""
        INSERT INTO validation_runs VALUES
        ('validation-1', 'snapshot-1', 'v1', '{}', current_timestamp, NULL)
        """)
    conn.execute("""
        INSERT INTO candidate_gate_results VALUES
        ('validation-1', 'candidate-b', 'sense.complete', TRUE, 'loser', '{}'),
        ('validation-1', 'candidate-a', 'sense.complete', FALSE, 'winner', '{}')
        """)

    monkeypatch.setattr(schema, "MIGRATIONS", all_migrations)
    schema.apply_migrations(conn)

    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)]
    assert conn.execute("SELECT candidate_id FROM content_candidates").fetchall() == [
        ("candidate-a",)
    ]
    assert conn.execute(
        "SELECT source_candidate_id FROM content_revisions ORDER BY revision_id"
    ).fetchall() == [("candidate-a",), ("candidate-a",)]
    assert conn.execute(
        "SELECT candidate_id FROM content_reviews ORDER BY review_id"
    ).fetchall() == [("candidate-a",), ("candidate-a",)]
    gate = conn.execute(
        "SELECT candidate_id, passed, message, details_json FROM candidate_gate_results"
    ).fetchone()
    assert gate[:2] == ("candidate-a", False)
    assert "winner" in gate[2]
    assert "loser" in gate[2]
    merged_details = json.loads(gate[3])
    assert [entry["candidate_id"] for entry in merged_details["merged_candidates"]] == [
        "candidate-a",
        "candidate-b",
    ]


def test_migration_v4_prefers_approved_duplicate_candidate(monkeypatch):
    conn = duckdb.connect(":memory:")
    all_migrations = schema.MIGRATIONS
    v3_migrations = [migration for migration in all_migrations if migration[0] <= 3]
    monkeypatch.setattr(schema, "MIGRATIONS", v3_migrations)
    schema.apply_migrations(conn)
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        [
            "source-1",
            "Source",
            "https://example.test",
            "1",
            "a" * 64,
            "CC-BY-4.0",
            "https://example.test/license",
            "Fixture",
            True,
            "approved",
        ],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "source-1", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-a', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 0.9, 'candidate', current_timestamp),
        ('candidate-b', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 1.0, 'approved', current_timestamp)
        """)
    conn.execute(
        "INSERT INTO canonical_content VALUES (?, ?, ?, current_timestamp)",
        ["content-1", "sense.book", "sense"],
    )
    conn.execute(
        """
        INSERT INTO content_revisions VALUES
        ('revision-b', 'content-1', 1, '{"stable_key":"sense.book"}', ?, 'approved', 'candidate-b', current_timestamp)
        """,
        ["c" * 64],
    )
    conn.execute("""
        INSERT INTO content_reviews VALUES
        ('review-b', 'candidate-b', 'revision-b', 'approved', 'reviewer', 'legacy', current_timestamp)
        """)

    monkeypatch.setattr(schema, "MIGRATIONS", all_migrations)
    schema.apply_migrations(conn)

    assert conn.execute(
        "SELECT candidate_id, state FROM content_candidates"
    ).fetchall() == [("candidate-b", "approved")]
    assert conn.execute(
        "SELECT source_candidate_id FROM content_revisions"
    ).fetchall() == [("candidate-b",)]
    assert conn.execute("SELECT candidate_id FROM content_reviews").fetchall() == [
        ("candidate-b",)
    ]


def test_migration_v4_quarantines_terminal_conflict_before_future_approval(
    monkeypatch, tmp_path: Path
):
    from src.learning.store import LearningGraphStore

    store = LearningGraphStore(tmp_path / "graph.duckdb")
    all_migrations = schema.MIGRATIONS
    v3_migrations = [migration for migration in all_migrations if migration[0] <= 3]
    monkeypatch.setattr(schema, "MIGRATIONS", v3_migrations)
    store.initialize()
    conn = store.connection()
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        [
            "source-1",
            "Source",
            "https://example.test",
            "1",
            "a" * 64,
            "CC-BY-4.0",
            "https://example.test/license",
            "Fixture",
            True,
            "approved",
        ],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "source-1", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-a', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 0.9, 'validated', current_timestamp),
        ('candidate-b', 'raw-1', 'sense', '{"stable_key":"sense.book"}', '{}', 1.0, 'rejected', current_timestamp)
        """)
    conn.execute("""
        INSERT INTO content_reviews VALUES
        ('review-b', 'candidate-b', NULL, 'rejected', 'reviewer', 'terminal failure', current_timestamp)
        """)

    monkeypatch.setattr(schema, "MIGRATIONS", all_migrations)
    schema.apply_migrations(conn)
    repository = ContentRepository(store)

    assert conn.execute(
        "SELECT candidate_id, state FROM content_candidates"
    ).fetchall() == [("candidate-a", "quarantined")]
    assert conn.execute(
        "SELECT candidate_id, decision, rationale FROM content_reviews"
    ).fetchall() == [("candidate-a", "rejected", "terminal failure")]
    with pytest.raises(ValueError, match="already been reviewed"):
        repository.review_candidate(
            "candidate-a", "approved", "reviewer-2", "Attempted approval"
        )


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
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)]

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
        ('candidate-b', 'raw-1', 'objective', '{\"variant\":1}', '{}', 1.0, 'candidate', current_timestamp)
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
        ('candidate-b', 'raw-1', 'objective', '{\"variant\":1}', '{}', 1.0, 'candidate', current_timestamp)
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


def test_migration_v7_creates_normalized_source_evidence_tables():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)

    assert (
        conn.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('lexical_source_evidence', 'lexical_word_evidence_links')
        ORDER BY table_name
        """).fetchall()
        == [
            ("lexical_source_evidence",),
            ("lexical_word_evidence_links",),
        ]
    )

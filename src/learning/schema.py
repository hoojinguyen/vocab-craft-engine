from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import duckdb

GRAPH_TABLES: tuple[str, ...] = (
    "graph_schema_migrations",
    "source_assets",
    "raw_reference_records",
    "content_candidates",
    "canonical_content",
    "content_revisions",
    "content_reviews",
    "content_edges",
)

MIGRATION_001 = """
CREATE TABLE IF NOT EXISTS graph_schema_migrations (
 version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS source_assets (
 asset_id TEXT PRIMARY KEY, title TEXT NOT NULL, locator TEXT NOT NULL,
 asset_version TEXT NOT NULL, sha256 TEXT NOT NULL, license_id TEXT NOT NULL,
 license_url TEXT NOT NULL, attribution TEXT NOT NULL,
 redistribution_allowed BOOLEAN NOT NULL, validation_status TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (validation_status IN ('candidate','approved','rejected','quarantined'))
);
CREATE TABLE IF NOT EXISTS raw_reference_records (
 raw_record_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES source_assets(asset_id),
 external_key TEXT NOT NULL, record_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL, import_run_id TEXT NOT NULL,
 imported_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(asset_id, external_key, payload_sha256)
);
CREATE TABLE IF NOT EXISTS content_candidates (
 candidate_id TEXT PRIMARY KEY, raw_record_id TEXT NOT NULL REFERENCES raw_reference_records(raw_record_id),
 content_type TEXT NOT NULL, normalized_payload_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 confidence DOUBLE NOT NULL, state TEXT NOT NULL DEFAULT 'candidate',
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (state IN ('candidate','approved','rejected','quarantined'))
);
CREATE TABLE IF NOT EXISTS canonical_content (
 content_id TEXT PRIMARY KEY, stable_key TEXT NOT NULL UNIQUE, content_type TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS content_revisions (
 revision_id TEXT PRIMARY KEY, content_id TEXT NOT NULL REFERENCES canonical_content(content_id),
 revision_number INTEGER NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 review_state TEXT NOT NULL, source_candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(content_id, revision_number),
 CHECK (review_state IN ('candidate','approved','rejected','quarantined'))
);
CREATE TABLE IF NOT EXISTS content_reviews (
 review_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
 revision_id TEXT REFERENCES content_revisions(revision_id), decision TEXT NOT NULL,
 reviewer_id TEXT NOT NULL, rationale TEXT NOT NULL,
 reviewed_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (decision IN ('approved','rejected','quarantined'))
);
CREATE TABLE IF NOT EXISTS content_edges (
 edge_id TEXT PRIMARY KEY, from_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
 to_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
 relation_type TEXT NOT NULL, attributes_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(from_revision_id, to_revision_id, relation_type)
);
"""

MIGRATION_002 = """
CREATE TABLE source_assets (
 asset_id TEXT PRIMARY KEY, title TEXT NOT NULL, locator TEXT NOT NULL,
 asset_version TEXT NOT NULL, sha256 TEXT NOT NULL, license_id TEXT NOT NULL,
 license_url TEXT NOT NULL, attribution TEXT NOT NULL,
 redistribution_allowed BOOLEAN NOT NULL, validation_status TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (validation_status IN ('candidate','approved','rejected','quarantined')),
 CHECK (
   validation_status <> 'approved'
   OR (
     trim(license_id) <> '' AND trim(attribution) <> ''
     AND redistribution_allowed = TRUE
   )
 )
);
CREATE TABLE raw_reference_records (
 raw_record_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES source_assets(asset_id),
 external_key TEXT NOT NULL, record_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL, import_run_id TEXT NOT NULL,
 imported_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(asset_id, external_key, payload_sha256)
);
CREATE TABLE content_candidates (
 candidate_id TEXT PRIMARY KEY, raw_record_id TEXT NOT NULL REFERENCES raw_reference_records(raw_record_id),
 content_type TEXT NOT NULL, normalized_payload_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 confidence DOUBLE NOT NULL, state TEXT NOT NULL DEFAULT 'candidate',
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (state IN ('candidate','approved','rejected','quarantined'))
);
CREATE TABLE canonical_content (
 content_id TEXT PRIMARY KEY, stable_key TEXT NOT NULL UNIQUE, content_type TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE content_revisions (
 revision_id TEXT PRIMARY KEY, content_id TEXT NOT NULL REFERENCES canonical_content(content_id),
 revision_number INTEGER NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 review_state TEXT NOT NULL, source_candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(content_id, revision_number),
 UNIQUE(revision_id, source_candidate_id),
 CHECK (review_state IN ('candidate','approved','rejected','quarantined'))
);
CREATE TABLE content_reviews (
 review_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
 revision_id TEXT, decision TEXT NOT NULL,
 reviewer_id TEXT NOT NULL, rationale TEXT NOT NULL,
 reviewed_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 FOREIGN KEY (revision_id, candidate_id)
   REFERENCES content_revisions(revision_id, source_candidate_id),
 CHECK (decision IN ('approved','rejected','quarantined'))
);
CREATE TABLE content_edges (
 edge_id TEXT PRIMARY KEY, from_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
 to_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
 relation_type TEXT NOT NULL, attributes_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(from_revision_id, to_revision_id, relation_type)
);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, MIGRATION_001), (2, MIGRATION_002)]

_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "source_assets": (
        "asset_id",
        "title",
        "locator",
        "asset_version",
        "sha256",
        "license_id",
        "license_url",
        "attribution",
        "redistribution_allowed",
        "validation_status",
        "created_at",
    ),
    "raw_reference_records": (
        "raw_record_id",
        "asset_id",
        "external_key",
        "record_type",
        "payload_json",
        "payload_sha256",
        "import_run_id",
        "imported_at",
    ),
    "content_candidates": (
        "candidate_id",
        "raw_record_id",
        "content_type",
        "normalized_payload_json",
        "evidence_json",
        "confidence",
        "state",
        "created_at",
    ),
    "canonical_content": (
        "content_id",
        "stable_key",
        "content_type",
        "created_at",
    ),
    "content_revisions": (
        "revision_id",
        "content_id",
        "revision_number",
        "payload_json",
        "payload_sha256",
        "review_state",
        "source_candidate_id",
        "created_at",
    ),
    "content_reviews": (
        "review_id",
        "candidate_id",
        "revision_id",
        "decision",
        "reviewer_id",
        "rationale",
        "reviewed_at",
    ),
    "content_edges": (
        "edge_id",
        "from_revision_id",
        "to_revision_id",
        "relation_type",
        "attributes_json",
    ),
}

_DROP_ORDER = (
    "content_edges",
    "content_reviews",
    "content_revisions",
    "canonical_content",
    "content_candidates",
    "raw_reference_records",
    "source_assets",
)

_RESTORE_ORDER = tuple(reversed(_DROP_ORDER))


def _snapshot_graph(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, list[tuple[Any, ...]]]:
    snapshots: dict[str, list[tuple[Any, ...]]] = {}
    for table, columns in _TABLE_COLUMNS.items():
        selected_columns = ", ".join(columns)
        snapshots[table] = conn.execute(
            f"SELECT {selected_columns} FROM {table}"
        ).fetchall()
    return snapshots


def _validate_legacy_reviews(
    snapshots: dict[str, list[tuple[Any, ...]]],
) -> None:
    revisions = {row[0]: row[6] for row in snapshots["content_revisions"]}
    for review in snapshots["content_reviews"]:
        review_id, candidate_id, revision_id = review[:3]
        if revision_id is None:
            continue
        source_candidate_id = revisions.get(revision_id)
        if source_candidate_id != candidate_id:
            raise RuntimeError(
                f"content review {review_id!r} candidate_id {candidate_id!r} "
                f"does not match revision {revision_id!r} source_candidate_id "
                f"{source_candidate_id!r}"
            )


def _quarantine_invalid_approved_sources(
    snapshots: dict[str, list[tuple[Any, ...]]],
) -> None:
    rows = snapshots["source_assets"]
    updated_rows: list[tuple[Any, ...]] = []
    for row in rows:
        row_values = list(row)
        if row_values[9] == "approved" and (
            not str(row_values[5]).strip()
            or not str(row_values[7]).strip()
            or not row_values[8]
        ):
            row_values[9] = "quarantined"
        updated_rows.append(tuple(row_values))
    snapshots["source_assets"] = updated_rows


def _restore_rows(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    rows: Iterable[tuple[Any, ...]],
) -> None:
    columns = _TABLE_COLUMNS[table]
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in rows:
        conn.execute(
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})",
            row,
        )


def _apply_migration_002(conn: duckdb.DuckDBPyConnection) -> None:
    snapshots = _snapshot_graph(conn)
    _validate_legacy_reviews(snapshots)
    _quarantine_invalid_approved_sources(snapshots)

    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE {table}")
    conn.execute(MIGRATION_002)
    for table in _RESTORE_ORDER:
        _restore_rows(conn, table, snapshots[table])


def apply_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Apply unapplied graph migrations in one transactional operation."""
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
            )
            """)
        applied_versions = {
            row[0]
            for row in conn.execute(
                "SELECT version FROM graph_schema_migrations"
            ).fetchall()
        }
        engine_versions = {version for version, _ in MIGRATIONS}
        newer_versions = applied_versions - engine_versions
        if newer_versions:
            newest = max(newer_versions)
            raise ValueError(
                f"database migration version {newest} is newer than engine version "
                f"{max(engine_versions)}"
            )

        for version, sql in MIGRATIONS:
            if version in applied_versions:
                continue
            if version == 2:
                _apply_migration_002(conn)
            else:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO graph_schema_migrations (version) VALUES (?)",
                [version],
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

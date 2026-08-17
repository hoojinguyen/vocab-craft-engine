from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import duckdb

GRAPH_TABLES: tuple[str, ...] = (
    "graph_schema_migrations",
    "source_assets",
    "source_snapshots",
    "raw_reference_records",
    "content_candidates",
    "canonical_content",
    "content_revisions",
    "content_reviews",
    "content_edges",
    "validation_runs",
    "candidate_gate_results",
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

MIGRATION_003 = """
CREATE TABLE content_candidates (
 candidate_id TEXT PRIMARY KEY, raw_record_id TEXT NOT NULL REFERENCES raw_reference_records(raw_record_id),
 content_type TEXT NOT NULL, normalized_payload_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 confidence DOUBLE NOT NULL, state TEXT NOT NULL DEFAULT 'candidate',
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (state IN ('candidate','validated','approved','rejected','quarantined'))
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
CREATE TABLE source_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 asset_id TEXT NOT NULL REFERENCES source_assets(asset_id),
 local_path TEXT NOT NULL,
 retrieved_at TIMESTAMP NOT NULL,
 file_sha256 TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(asset_id, file_sha256)
);
CREATE TABLE validation_runs (
 validation_run_id TEXT PRIMARY KEY,
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
 policy_version TEXT NOT NULL,
 selection_json TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 completed_at TIMESTAMP
);
CREATE TABLE candidate_gate_results (
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
 gate_code TEXT NOT NULL,
 passed BOOLEAN NOT NULL,
 message TEXT NOT NULL,
 details_json TEXT NOT NULL,
 PRIMARY KEY(validation_run_id, candidate_id, gate_code)
);
"""

MIGRATION_004 = """
CREATE UNIQUE INDEX IF NOT EXISTS content_candidates_identity_idx
ON content_candidates (raw_record_id, content_type, normalized_payload_json);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, MIGRATION_001),
    (2, MIGRATION_002),
    (3, MIGRATION_003),
    (4, MIGRATION_004),
]

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
    "source_snapshots": (
        "snapshot_id",
        "asset_id",
        "local_path",
        "retrieved_at",
        "file_sha256",
        "created_at",
    ),
    "validation_runs": (
        "validation_run_id",
        "snapshot_id",
        "policy_version",
        "selection_json",
        "created_at",
        "completed_at",
    ),
    "candidate_gate_results": (
        "validation_run_id",
        "candidate_id",
        "gate_code",
        "passed",
        "message",
        "details_json",
    ),
}

_MIGRATION_002_TABLES = (
    "source_assets",
    "raw_reference_records",
    "content_candidates",
    "canonical_content",
    "content_revisions",
    "content_reviews",
    "content_edges",
)

_CONTENT_CANDIDATE_GRAPH_TABLES = (
    "content_candidates",
    "canonical_content",
    "content_revisions",
    "content_reviews",
    "content_edges",
)

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

_MIGRATION_003_DROP_ORDER = (
    "content_edges",
    "content_reviews",
    "content_revisions",
    "canonical_content",
    "content_candidates",
)

_MIGRATION_003_RESTORE_ORDER = tuple(reversed(_MIGRATION_003_DROP_ORDER))

_MIGRATION_004_SNAPSHOT_TABLES = (
    "content_edges",
    "content_reviews",
    "content_revisions",
    "canonical_content",
    "content_candidates",
    "source_snapshots",
    "validation_runs",
    "candidate_gate_results",
)

_MIGRATION_004_DROP_ORDER = (
    "candidate_gate_results",
    "content_edges",
    "content_reviews",
    "content_revisions",
    "canonical_content",
    "content_candidates",
    "validation_runs",
    "source_snapshots",
)

_MIGRATION_004_RESTORE_ORDER = (
    "source_snapshots",
    "validation_runs",
    "content_candidates",
    "canonical_content",
    "content_revisions",
    "content_reviews",
    "content_edges",
    "candidate_gate_results",
)

_CANDIDATE_STATE_PRIORITY = {
    "approved": 4,
    "validated": 3,
    "candidate": 2,
    "quarantined": 1,
    "rejected": 1,
}


def _snapshot_graph(
    conn: duckdb.DuckDBPyConnection,
    tables: Iterable[str],
) -> dict[str, list[tuple[Any, ...]]]:
    snapshots: dict[str, list[tuple[Any, ...]]] = {}
    for table in tables:
        columns = _TABLE_COLUMNS[table]
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
    snapshots = _snapshot_graph(conn, _MIGRATION_002_TABLES)
    _validate_legacy_reviews(snapshots)
    _quarantine_invalid_approved_sources(snapshots)

    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE {table}")
    conn.execute(MIGRATION_002)
    for table in _RESTORE_ORDER:
        _restore_rows(conn, table, snapshots[table])


def _apply_migration_003(conn: duckdb.DuckDBPyConnection) -> None:
    snapshots = _snapshot_graph(conn, _CONTENT_CANDIDATE_GRAPH_TABLES)

    for table in _MIGRATION_003_DROP_ORDER:
        conn.execute(f"DROP TABLE {table}")
    conn.execute(MIGRATION_003)
    for table in _MIGRATION_003_RESTORE_ORDER:
        _restore_rows(conn, table, snapshots[table])


def _candidate_identity_duplicates(conn: duckdb.DuckDBPyConnection) -> bool:
    return conn.execute("""
            SELECT 1
            FROM content_candidates
            GROUP BY raw_record_id, content_type, normalized_payload_json
            HAVING count(*) > 1
            LIMIT 1
            """).fetchone() is not None


def _merge_duplicate_candidates(
    snapshots: dict[str, list[tuple[Any, ...]]],
) -> None:
    candidates_by_identity: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
    for row in snapshots["content_candidates"]:
        candidates_by_identity.setdefault(tuple(row[1:4]), []).append(row)

    winners: dict[tuple[Any, ...], str] = {}
    redirects: dict[str, str] = {}
    retained_candidates: list[tuple[Any, ...]] = []
    for identity in sorted(candidates_by_identity, key=str):
        rows = sorted(
            candidates_by_identity[identity],
            key=lambda item: (
                -_CANDIDATE_STATE_PRIORITY.get(str(item[6]), -1),
                str(item[0]),
            ),
        )
        winner = str(rows[0][0])
        winners[identity] = winner
        retained_candidates.append(rows[0])
        for row in rows[1:]:
            redirects[str(row[0])] = winner
    snapshots["content_candidates"] = retained_candidates

    merged_gates: dict[tuple[Any, ...], tuple[list[Any], list[dict[str, object]]]] = {}
    for row in sorted(
        snapshots["candidate_gate_results"],
        key=lambda item: (str(item[0]), str(item[1]), str(item[2])),
    ):
        original_candidate_id = str(row[1])
        row_values = list(row)
        row_values[1] = redirects.get(original_candidate_id, original_candidate_id)
        gate_key = (row_values[0], row_values[1], row_values[2])
        detail_entry: dict[str, object] = {
            "candidate_id": original_candidate_id,
            "passed": bool(row[3]),
            "message": str(row[4]),
            "details": _decode_gate_details(row[5]),
        }
        existing = merged_gates.get(gate_key)
        if existing is None:
            merged_gates[gate_key] = (row_values, [detail_entry])
            continue
        merged_row, detail_entries = existing
        merged_row[3] = bool(merged_row[3]) and bool(row[3])
        messages = [str(merged_row[4]), str(row[4])]
        merged_row[4] = "; ".join(
            dict.fromkeys(message for message in messages if message)
        )
        detail_entries.append(detail_entry)
        merged_row[5] = _encode_gate_details(detail_entries)
    snapshots["candidate_gate_results"] = [
        tuple(row_values) for row_values, _ in merged_gates.values()
    ]

    revisions = []
    for row in snapshots["content_revisions"]:
        row_values = list(row)
        row_values[6] = redirects.get(str(row_values[6]), str(row_values[6]))
        revisions.append(tuple(row_values))
    snapshots["content_revisions"] = revisions

    reviews = []
    for row in snapshots["content_reviews"]:
        row_values = list(row)
        row_values[1] = redirects.get(str(row_values[1]), str(row_values[1]))
        reviews.append(tuple(row_values))
    snapshots["content_reviews"] = reviews


def _decode_gate_details(details_json: Any) -> object:
    try:
        return json.loads(str(details_json))
    except (TypeError, ValueError):
        return str(details_json)


def _encode_gate_details(entries: list[dict[str, object]]) -> str:
    return json.dumps(
        {"merged_candidates": entries},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _apply_migration_004(conn: duckdb.DuckDBPyConnection) -> None:
    if not _candidate_identity_duplicates(conn):
        conn.execute(MIGRATION_004)
        return

    snapshots = _snapshot_graph(conn, _MIGRATION_004_SNAPSHOT_TABLES)
    _merge_duplicate_candidates(snapshots)
    for table in _MIGRATION_004_DROP_ORDER:
        conn.execute(f"DROP TABLE {table}")
    conn.execute(MIGRATION_003)
    for table in _MIGRATION_004_RESTORE_ORDER:
        _restore_rows(conn, table, snapshots[table])
    conn.execute(MIGRATION_004)


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
            elif version == 3:
                _apply_migration_003(conn)
            elif version == 4:
                _apply_migration_004(conn)
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

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
    "lexical_definition_inputs",
    "lexical_evidence_items",
    "lexical_source_evidence",
    "lexical_word_evidence_links",
    "lexical_evidence_rankings",
    "lexical_input_canonical_map",
    "lexical_input_dispositions",
    "lexical_remediation_attempts",
    "lexical_quarantine_cases",
    "lexical_run_checkpoints",
    "lexical_release_builds",
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

MIGRATION_005 = """
CREATE TABLE IF NOT EXISTS lexical_definition_inputs (
 input_id TEXT PRIMARY KEY,
 snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
 raw_record_id TEXT NOT NULL UNIQUE REFERENCES raw_reference_records(raw_record_id),
 source_word_id BIGINT NOT NULL CHECK (source_word_id > 0),
 source_definition_id BIGINT NOT NULL CHECK (source_definition_id > 0),
 input_key TEXT NOT NULL UNIQUE,
 source_definition_sha256 TEXT NOT NULL,
 lemma TEXT NOT NULL,
 pos TEXT NOT NULL,
 frequency_rank BIGINT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS lexical_evidence_items (
 evidence_id TEXT PRIMARY KEY,
 input_id TEXT NOT NULL REFERENCES lexical_definition_inputs(input_id),
 evidence_role TEXT NOT NULL,
 source_row_id BIGINT NOT NULL CHECK (source_row_id > 0),
 source_name TEXT NOT NULL,
 value_json TEXT NOT NULL,
 value_sha256 TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(input_id, evidence_role, source_row_id, value_sha256),
 CHECK (evidence_role IN ('definition', 'translation', 'ipa', 'example'))
);
CREATE TABLE IF NOT EXISTS lexical_evidence_rankings (
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 input_id TEXT NOT NULL REFERENCES lexical_definition_inputs(input_id),
 evidence_id TEXT NOT NULL REFERENCES lexical_evidence_items(evidence_id),
 evidence_role TEXT NOT NULL,
 rank BIGINT NOT NULL,
 selected BOOLEAN NOT NULL,
 eligible BOOLEAN NOT NULL,
 reason_json TEXT NOT NULL,
 PRIMARY KEY(validation_run_id, input_id, evidence_id),
 CHECK (evidence_role IN ('definition', 'translation', 'ipa', 'example'))
);
CREATE TABLE IF NOT EXISTS lexical_input_canonical_map (
 input_id TEXT PRIMARY KEY REFERENCES lexical_definition_inputs(input_id),
 canonical_key TEXT NOT NULL,
 candidate_id TEXT REFERENCES content_candidates(candidate_id),
 mapped_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS lexical_input_dispositions (
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 input_id TEXT NOT NULL REFERENCES lexical_definition_inputs(input_id),
 state TEXT NOT NULL,
 candidate_id TEXT REFERENCES content_candidates(candidate_id),
 failure_codes_json TEXT NOT NULL,
 rationale_json TEXT NOT NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 PRIMARY KEY(validation_run_id, input_id),
 CHECK (state IN ('validated', 'quarantined', 'rejected'))
);
CREATE TABLE IF NOT EXISTS lexical_remediation_attempts (
 attempt_id TEXT PRIMARY KEY,
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 input_id TEXT NOT NULL REFERENCES lexical_definition_inputs(input_id),
 attempt_number BIGINT NOT NULL,
 selection_json TEXT NOT NULL,
 outcome TEXT NOT NULL,
 failure_codes_json TEXT NOT NULL,
 rationale_json TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 UNIQUE(validation_run_id, input_id, attempt_number),
 CHECK (outcome IN ('validated', 'quarantined', 'rejected'))
);
CREATE TABLE IF NOT EXISTS lexical_quarantine_cases (
 case_id TEXT PRIMARY KEY,
 input_id TEXT NOT NULL UNIQUE REFERENCES lexical_definition_inputs(input_id),
 latest_validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 status TEXT NOT NULL,
 retry_count BIGINT NOT NULL,
 failure_codes_json TEXT NOT NULL,
 alternatives_json TEXT NOT NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 CHECK (status IN ('open', 'resolved', 'rejected'))
);
CREATE TABLE IF NOT EXISTS lexical_run_checkpoints (
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 phase TEXT NOT NULL,
 last_input_key TEXT,
 processed_count BIGINT NOT NULL,
 completed_at TIMESTAMP,
 updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
 PRIMARY KEY(validation_run_id, phase)
);
CREATE TABLE IF NOT EXISTS lexical_release_builds (
 release_build_id TEXT PRIMARY KEY,
 validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
 release_version TEXT NOT NULL UNIQUE,
 manifest_sha256 TEXT NOT NULL,
 counts_json TEXT NOT NULL,
 output_path TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS lexical_definition_inputs_enumeration_idx
ON lexical_definition_inputs (snapshot_id, frequency_rank, input_key);
CREATE INDEX IF NOT EXISTS lexical_evidence_items_lookup_idx
ON lexical_evidence_items (input_id, evidence_role);
CREATE INDEX IF NOT EXISTS lexical_input_dispositions_run_idx
ON lexical_input_dispositions (validation_run_id, state, input_id);
CREATE INDEX IF NOT EXISTS lexical_quarantine_cases_open_idx
ON lexical_quarantine_cases (status, updated_at, input_id);
"""

MIGRATION_006 = MIGRATION_005.replace(
    "frequency_rank BIGINT NOT NULL,",
    "frequency_rank BIGINT NOT NULL CHECK (frequency_rank BETWEEN 1 AND 3500),",
)

MIGRATION_007 = """
CREATE TABLE IF NOT EXISTS lexical_source_evidence (
    source_evidence_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    evidence_role TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_row_id BIGINT NOT NULL CHECK (source_row_id > 0),
    source_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    value_sha256 TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(snapshot_id, evidence_role, source_table, source_row_id, value_sha256),
    CHECK (evidence_role IN ('definition', 'translation', 'ipa', 'example'))
);
CREATE TABLE IF NOT EXISTS lexical_word_evidence_links (
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    source_word_id BIGINT NOT NULL CHECK (source_word_id > 0),
    source_evidence_id TEXT NOT NULL REFERENCES lexical_source_evidence(source_evidence_id),
    link_rank BIGINT NOT NULL CHECK (link_rank > 0),
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY(snapshot_id, source_word_id, source_evidence_id)
);
CREATE INDEX IF NOT EXISTS lexical_source_evidence_lookup_idx
ON lexical_source_evidence (snapshot_id, evidence_role, source_row_id);
CREATE INDEX IF NOT EXISTS lexical_word_evidence_links_lookup_idx
ON lexical_word_evidence_links (snapshot_id, source_word_id, link_rank);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, MIGRATION_001),
    (2, MIGRATION_002),
    (3, MIGRATION_003),
    (4, MIGRATION_004),
    (5, MIGRATION_005),
    (6, MIGRATION_006),
    (7, MIGRATION_007),
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

_MIGRATION_006_TABLES = (
    "lexical_definition_inputs",
    "lexical_evidence_items",
    "lexical_evidence_rankings",
    "lexical_input_canonical_map",
    "lexical_input_dispositions",
    "lexical_remediation_attempts",
    "lexical_quarantine_cases",
    "lexical_run_checkpoints",
    "lexical_release_builds",
)

_MIGRATION_006_DROP_ORDER = (
    "lexical_evidence_rankings",
    "lexical_input_canonical_map",
    "lexical_input_dispositions",
    "lexical_remediation_attempts",
    "lexical_quarantine_cases",
    "lexical_evidence_items",
    "lexical_definition_inputs",
    "lexical_run_checkpoints",
    "lexical_release_builds",
)

_MIGRATION_006_RESTORE_ORDER = _MIGRATION_006_TABLES

_CANDIDATE_STATE_PRIORITY = {
    "approved": 4,
    "validated": 3,
    "candidate": 2,
    "quarantined": 1,
    "rejected": 1,
}
_TERMINAL_CANDIDATE_STATES = frozenset({"rejected", "quarantined"})


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
        winner_row = list(rows[0])
        states = {str(row[6]) for row in rows}
        terminal_states = states & _TERMINAL_CANDIDATE_STATES
        if terminal_states and (
            states - _TERMINAL_CANDIDATE_STATES or len(terminal_states) > 1
        ):
            winner_row[6] = "quarantined"
        retained_candidates.append(tuple(winner_row))
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


def _snapshot_tables(
    conn: duckdb.DuckDBPyConnection, tables: Iterable[str]
) -> dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]]:
    snapshots: dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]] = {}
    for table in tables:
        columns = tuple(
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        )
        column_list = ", ".join(columns)
        snapshots[table] = (
            columns,
            conn.execute(f"SELECT {column_list} FROM {table}").fetchall(),
        )
    return snapshots


def _restore_table_snapshot(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    snapshot: tuple[tuple[str, ...], list[tuple[Any, ...]]],
) -> None:
    columns, rows = snapshot
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in rows:
        conn.execute(
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})", row
        )


def _rekey_migration_006_input_keys(
    conn: duckdb.DuckDBPyConnection,
    snapshots: dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]],
) -> None:
    columns, rows = snapshots["lexical_definition_inputs"]
    column_indexes = {column: index for index, column in enumerate(columns)}
    input_id_index = column_indexes["input_id"]
    snapshot_id_index = column_indexes["snapshot_id"]
    input_key_index = column_indexes["input_key"]
    lineage_rows = conn.execute("""
        SELECT inputs.input_id, snapshots.asset_id, inputs.snapshot_id,
               raw_records.asset_id, raw_records.external_key
        FROM lexical_definition_inputs AS inputs
        LEFT JOIN source_snapshots AS snapshots
          ON snapshots.snapshot_id = inputs.snapshot_id
        LEFT JOIN raw_reference_records AS raw_records
          ON raw_records.raw_record_id = inputs.raw_record_id
        """).fetchall()
    lineage_by_input_id: dict[str, tuple[str, str, str]] = {}
    for input_id, asset_id, snapshot_id, raw_asset_id, external_key in lineage_rows:
        if (
            input_id is None
            or asset_id is None
            or snapshot_id is None
            or raw_asset_id is None
            or external_key is None
        ):
            raise ValueError("cannot rekey lexical input without source lineage")
        if str(asset_id) != str(raw_asset_id):
            raise ValueError(
                "cannot rekey lexical input with mismatched source lineage"
            )
        input_id_text = str(input_id)
        if input_id_text in lineage_by_input_id:
            raise ValueError("cannot rekey lexical input with ambiguous source lineage")
        lineage_by_input_id[input_id_text] = (
            str(asset_id),
            str(snapshot_id),
            str(external_key),
        )

    input_ids = {str(row[input_id_index]) for row in rows}
    if input_ids != set(lineage_by_input_id):
        raise ValueError("cannot rekey lexical input without complete source lineage")

    rekeyed_rows: list[tuple[Any, ...]] = []
    rekeyed_input_keys: set[str] = set()
    rekeyed_input_keys_by_legacy_key: dict[str, str] = {}
    for row in rows:
        input_id = str(row[input_id_index])
        asset_id, snapshot_id, external_key = lineage_by_input_id[input_id]
        if str(row[snapshot_id_index]) != snapshot_id:
            raise ValueError("cannot rekey lexical input with ambiguous source lineage")
        input_key = f"{asset_id}:{snapshot_id}:{external_key}"
        if input_key in rekeyed_input_keys:
            raise ValueError(f"lexical input rekey collision for {input_key!r}")
        rekeyed_input_keys.add(input_key)
        legacy_input_key = str(row[input_key_index])
        rekeyed_input_keys_by_legacy_key[legacy_input_key] = input_key
        row_values = list(row)
        row_values[input_key_index] = input_key
        rekeyed_rows.append(tuple(row_values))
    snapshots["lexical_definition_inputs"] = (columns, rekeyed_rows)

    checkpoint_columns, checkpoint_rows = snapshots["lexical_run_checkpoints"]
    checkpoint_indexes = {
        column: index for index, column in enumerate(checkpoint_columns)
    }
    last_input_key_index = checkpoint_indexes["last_input_key"]
    rekeyed_checkpoints: list[tuple[Any, ...]] = []
    for row in checkpoint_rows:
        row_values = list(row)
        last_input_key = row_values[last_input_key_index]
        if last_input_key is not None:
            row_values[last_input_key_index] = rekeyed_input_keys_by_legacy_key.get(
                str(last_input_key), str(last_input_key)
            )
        rekeyed_checkpoints.append(tuple(row_values))
    snapshots["lexical_run_checkpoints"] = (checkpoint_columns, rekeyed_checkpoints)


def _apply_migration_006(conn: duckdb.DuckDBPyConnection) -> None:
    invalid_rank = conn.execute("""
        SELECT frequency_rank FROM lexical_definition_inputs
        WHERE frequency_rank < 1 OR frequency_rank > 3500
        LIMIT 1
        """).fetchone()
    if invalid_rank is not None:
        raise ValueError(
            "cannot enforce lexical rank scope for existing frequency rank "
            f"{invalid_rank[0]!r}"
        )
    snapshots = _snapshot_tables(conn, _MIGRATION_006_TABLES)
    _rekey_migration_006_input_keys(conn, snapshots)
    for table in _MIGRATION_006_DROP_ORDER:
        conn.execute(f"DROP TABLE {table}")
    conn.execute(MIGRATION_006)
    for table in _MIGRATION_006_RESTORE_ORDER:
        _restore_table_snapshot(conn, table, snapshots[table])


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
            elif version == 6:
                _apply_migration_006(conn)
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

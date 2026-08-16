GRAPH_TABLES = (
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
 CHECK (validation_status IN ('candidate','approved','rejected','quarantined')),
 CHECK (
   validation_status <> 'approved'
   OR (
     trim(license_id) <> '' AND trim(attribution) <> ''
     AND redistribution_allowed = TRUE
   )
 )
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

MIGRATIONS = [(1, MIGRATION_001)]

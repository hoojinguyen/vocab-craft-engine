CURRICULUM_PACK_SCHEMA = """
CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE content_revisions (
    revision_id TEXT PRIMARY KEY, content_id TEXT NOT NULL, stable_key TEXT NOT NULL,
    content_type TEXT NOT NULL, revision_number INTEGER NOT NULL,
    payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL
);
CREATE TABLE content_edges (
    edge_id TEXT PRIMARY KEY,
    from_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
    to_revision_id TEXT NOT NULL REFERENCES content_revisions(revision_id),
    relation_type TEXT NOT NULL, attributes_json TEXT NOT NULL
);
CREATE TABLE source_attributions (
    asset_id TEXT PRIMARY KEY, title TEXT NOT NULL, license_id TEXT NOT NULL,
    license_url TEXT NOT NULL, attribution TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE quality_gate_results (
    gate_code TEXT NOT NULL, passed INTEGER NOT NULL, message TEXT NOT NULL,
    revision_id TEXT, PRIMARY KEY (gate_code, revision_id)
);
"""

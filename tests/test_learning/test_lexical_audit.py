from __future__ import annotations

import hashlib
import json

import pytest

from src.learning.catalog import RawRecordInput, SourceCatalog
from src.learning.lexical_audit import LexicalAuditService


def _raw_bundle(
    lemma: str,
    definition_en: str,
    definition_vi: str,
    *,
    frequency_rank: int,
    ipa_uk: str | None = "/bʊk/",
    ipa_us: str | None = "/bʊk/",
) -> dict[str, object]:
    return {
        "word": {
            "lemma": lemma,
            "pos": "noun",
            "frequency_rank": frequency_rank,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "source": "kaikki",
        },
        "definitions": [
            {"definition_en": definition_en, "definition_vi": definition_vi}
        ],
        "examples": [
            {
                "text_en": f"Read this {lemma}.",
                "text_vi": f"Hãy đọc {lemma} này.",
                "source": "tatoeba",
            }
        ],
    }


def _seed_snapshot_and_bundles(catalog: SourceCatalog) -> None:
    with catalog.store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_snapshots (
                snapshot_id, asset_id, local_path, retrieved_at, file_sha256
            ) VALUES (?, ?, ?, current_timestamp, ?)
            """,
            ["snapshot-1", "human-authored-a0", "/tmp/lexical.db", "a" * 64],
        )

    catalog.append_raw_records(
        [
            RawRecordInput(
                asset_id="human-authored-a0",
                external_key="sqlite-lexical:book",
                record_type="sqlite_lexical_bundle",
                payload=_raw_bundle(
                    "book", "A set of written pages.", "quyển sách", frequency_rank=100
                ),
                import_run_id="import-1",
            ),
            RawRecordInput(
                asset_id="human-authored-a0",
                external_key="sqlite-lexical:same",
                record_type="sqlite_lexical_bundle",
                payload=_raw_bundle(
                    "same",
                    "Identical in kind or value.",
                    "Identical in kind or value.",
                    frequency_rank=501,
                ),
                import_run_id="import-1",
            ),
            RawRecordInput(
                asset_id="human-authored-a0",
                external_key="sqlite-lexical:paper",
                record_type="sqlite_lexical_bundle",
                payload=_raw_bundle(
                    "paper",
                    "Material used for writing.",
                    "giấy",
                    frequency_rank=1501,
                    ipa_uk=None,
                    ipa_us=None,
                ),
                import_run_id="import-1",
            ),
        ]
    )


def test_lexical_audit_projects_senses_persists_gates_and_quarantines_failures(
    graph_catalog: SourceCatalog,
):
    _seed_snapshot_and_bundles(graph_catalog)

    audit = LexicalAuditService(graph_catalog.store).audit("snapshot-1")

    definition_hash = hashlib.sha256(b"A set of written pages.").hexdigest()[:12]
    rows = graph_catalog.store.connection().execute("""
        SELECT candidate_id, normalized_payload_json, state
        FROM content_candidates
        ORDER BY normalized_payload_json
        """).fetchall()
    payloads_by_lemma = {
        json.loads(payload_json)["lemma"]: (
            candidate_id,
            json.loads(payload_json),
            state,
        )
        for candidate_id, payload_json, state in rows
    }

    assert audit.candidate_state_counts == {"quarantined": 2, "validated": 1}
    assert audit.gate_code_counts == {
        "sense.complete": 1,
        "sense.ipa_missing": 1,
        "sense.translation_passthrough": 1,
    }
    assert payloads_by_lemma["book"][1] == {
        "stable_key": f"sense.book.noun.{definition_hash}",
        "lemma": "book",
        "pos": "noun",
        "frequency_rank": 100,
        "cefr_level": "A1",
        "cefr_method": "frequency_rank_v1",
        "definition_en": "A set of written pages.",
        "definition_vi": "quyển sách",
        "ipa_uk": "/bʊk/",
        "ipa_us": "/bʊk/",
        "ipa_source": "kaikki",
        "ipa_confidence": 0.8,
        "examples": [
            {
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc book này.",
                "source": "tatoeba",
            }
        ],
        "source_asset_id": "human-authored-a0",
    }
    assert payloads_by_lemma["book"][2] == "validated"
    assert payloads_by_lemma["same"][2] == "quarantined"
    assert payloads_by_lemma["paper"][2] == "quarantined"
    assert (
        graph_catalog.store.connection().execute("""
        SELECT reviewer_id, rationale
        FROM content_reviews
        ORDER BY rationale
        """).fetchall()
        == [
            ("validator:lexical-v1", "sense.ipa_missing"),
            ("validator:lexical-v1", "sense.translation_passthrough"),
        ]
    )
    assert (
        graph_catalog.store.connection()
        .execute(
            """
        SELECT policy_version, selection_json, completed_at IS NOT NULL
        FROM validation_runs
        WHERE validation_run_id = ?
        """,
            [audit.validation_run_id],
        )
        .fetchone()
        == (
            "lexical-v1",
            '{"content_type":"sense","record_type":"sqlite_lexical_bundle"}',
            True,
        )
    )


def test_lexical_audit_is_idempotent_for_existing_raw_bundles_and_candidates(
    graph_catalog: SourceCatalog,
):
    _seed_snapshot_and_bundles(graph_catalog)
    service = LexicalAuditService(graph_catalog.store)

    first = service.audit("snapshot-1")
    second = service.audit("snapshot-1")

    assert second.validation_run_id != first.validation_run_id
    assert second.candidate_state_counts == first.candidate_state_counts
    assert second.gate_code_counts == first.gate_code_counts
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records")
        == 3
    )
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM content_candidates") == 3
    )
    assert graph_catalog.store.fetch_value("SELECT count(*) FROM validation_runs") == 2
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM candidate_gate_results")
        == 6
    )


def test_lexical_audit_rejects_a_non_object_raw_bundle():
    with pytest.raises(TypeError, match="must be an object"):
        LexicalAuditService._decode_bundle("[]")

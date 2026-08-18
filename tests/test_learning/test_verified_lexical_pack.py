from __future__ import annotations

from typing import Any

import pytest

from src.learning.lexical_remediation import LexicalRemediationService
from src.learning.repository import ContentRepository
from tests.test_learning.test_lexical_evidence import _append_input, _snapshot


def _input_candidates(store, validation_run_id: str) -> dict[str, str]:
    rows = (
        store.connection()
        .execute(
            """
        SELECT input_id, candidate_id
        FROM lexical_input_dispositions
        WHERE validation_run_id = ?
        ORDER BY input_id
        """,
            [validation_run_id],
        )
        .fetchall()
    )
    return {str(input_id): str(candidate_id) for input_id, candidate_id in rows}


def seed_resolved_release_graph(graph_catalog) -> dict[str, Any]:
    """Create two approved duplicate senses plus one explicitly rejected input."""
    snapshot_id = _snapshot(graph_catalog)
    approved_input_ids = [
        _append_input(
            graph_catalog,
            snapshot_id,
            external_key=f"verified:book:{index}",
            word_id=index,
            definition_id=index,
            examples=[
                {
                    "id": index,
                    "source_row_id": index,
                    "text_en": "Read this book.",
                    "text_vi": "Hãy đọc quyển sách này.",
                    "source": "tatoeba",
                }
            ],
        )
        for index in (10, 11)
    ]
    rejected_input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="verified:book:rejected",
        word_id=12,
        definition_id=12,
        definition_en="a written work",
        examples=[
            {
                "id": 12,
                "source_row_id": 12,
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    )
    validation_run_id = "verified-release-run"
    LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id=validation_run_id
    )
    repository = ContentRepository(graph_catalog.store)
    candidates = _input_candidates(graph_catalog.store, validation_run_id)
    for input_id in approved_input_ids:
        revision_id = repository.review_candidate(
            candidates[input_id], "approved", "fixture-reviewer", "Approved fixture"
        )
        assert revision_id is not None
    repository.review_candidate(
        candidates[rejected_input_id],
        "rejected",
        "fixture-reviewer",
        "Rejected fixture",
    )
    graph_catalog.store.connection().execute(
        """
        UPDATE lexical_input_dispositions
        SET state = 'rejected', failure_codes_json = '["editorial.rejected"]'
        WHERE validation_run_id = ? AND input_id = ?
        """,
        [validation_run_id, rejected_input_id],
    )
    raw_rows = (
        graph_catalog.store.connection()
        .execute(
            """
        SELECT input_id, raw_record_id
        FROM lexical_definition_inputs
        WHERE input_id IN (?, ?, ?)
        ORDER BY input_id
        """,
            [*approved_input_ids, rejected_input_id],
        )
        .fetchall()
    )
    raw_ids = {
        str(input_id): str(raw_record_id) for input_id, raw_record_id in raw_rows
    }
    return {
        "snapshot_id": snapshot_id,
        "validation_run_id": validation_run_id,
        "approved_input_ids": tuple(approved_input_ids),
        "rejected_input_id": rejected_input_id,
        "raw_ids": raw_ids,
    }


def test_verified_pack_blocks_an_empty_lexical_graph(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    snapshot_id = _snapshot(graph_catalog)
    graph_catalog.store.connection().execute(
        """
        INSERT INTO validation_runs (
            validation_run_id, snapshot_id, policy_version, selection_json
        ) VALUES ('empty-release-run', ?, 'fixture-v1', '{}')
        """,
        [snapshot_id],
    )
    with pytest.raises(ValueError, match="no lexical inputs"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            "empty-release-run", "v1"
        )


def test_verified_pack_blocks_a_merely_validated_candidate(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    snapshot_id = _snapshot(graph_catalog)
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="validated-only",
        word_id=1,
        definition_id=1,
        examples=[
            {
                "id": 1,
                "source_row_id": 1,
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    )
    LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="validated-only-run"
    )

    with pytest.raises(ValueError, match="approved"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            "validated-only-run", "v1"
        )


def test_verified_pack_blocks_an_open_quarantine_case(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)
    graph_catalog.store.connection().execute(
        """
        INSERT INTO lexical_quarantine_cases (
            case_id, input_id, latest_validation_run_id, status, retry_count,
            failure_codes_json, alternatives_json
        ) VALUES ('open-case', ?, ?, 'open', 0, '[]', '[]')
        """,
        [seeded["approved_input_ids"][0], seeded["validation_run_id"]],
    )

    with pytest.raises(ValueError, match="open quarantine"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            seeded["validation_run_id"], "v1"
        )


def test_verified_pack_blocks_a_missing_disposition(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    snapshot_id = _snapshot(graph_catalog)
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="missing-disposition",
        word_id=1,
        definition_id=1,
    )
    graph_catalog.store.connection().execute(
        """
        INSERT INTO validation_runs (
            validation_run_id, snapshot_id, policy_version, selection_json
        ) VALUES ('missing-disposition-run', ?, 'fixture-v1', '{}')
        """,
        [snapshot_id],
    )

    with pytest.raises(ValueError, match="missing dispositions"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            "missing-disposition-run", "v1"
        )


def test_verified_pack_blocks_mismatched_reconciliation_total(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)
    other_snapshot_id = "other-snapshot"
    with graph_catalog.store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_snapshots (
                snapshot_id, asset_id, local_path, retrieved_at, file_sha256
            ) VALUES (?, 'human-authored-a0', '/tmp/other.db', current_timestamp, ?)
            """,
            [other_snapshot_id, "b" * 64],
        )
    other_input_id = _append_input(
        graph_catalog,
        other_snapshot_id,
        external_key="other-snapshot-input",
        word_id=99,
        definition_id=99,
    )
    graph_catalog.store.connection().execute(
        """
        INSERT INTO lexical_input_dispositions (
            validation_run_id, input_id, state, failure_codes_json, rationale_json
        ) VALUES (?, ?, 'rejected', '[]', '{}')
        """,
        [seeded["validation_run_id"], other_input_id],
    )

    with pytest.raises(ValueError, match="reconciliation"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            seeded["validation_run_id"], "v1"
        )


def test_verified_pack_composes_one_approved_sense_and_all_approved_provenance(
    graph_catalog,
):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)

    pack = VerifiedLexicalPackComposer(graph_catalog.store).compose(
        seeded["validation_run_id"], "v1"
    )

    assert len(pack.senses) == 1
    assert {item["raw_record_id"] for item in pack.provenance} == {
        seeded["raw_ids"][input_id] for input_id in seeded["approved_input_ids"]
    }
    assert pack.reconciliation == {
        "approved_candidate_count": 2,
        "approved_provenance_count": 2,
        "approved_sense_count": 1,
        "input_total": 3,
        "quarantined_input_count": 0,
        "rejected_input_count": 1,
        "validated_input_count": 2,
    }


def test_verified_pack_uses_only_the_evidence_gated_candidate_payload(
    graph_catalog,
):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)
    repository = ContentRepository(graph_catalog.store)
    candidate_id = _input_candidates(graph_catalog.store, seeded["validation_run_id"])[
        seeded["approved_input_ids"][0]
    ]
    original_revision_id = graph_catalog.store.fetch_value(
        """
        SELECT revision_id FROM content_revisions
        WHERE source_candidate_id = ?
        ORDER BY revision_number
        LIMIT 1
        """,
        [candidate_id],
    )
    assert original_revision_id is not None
    changed_payload = repository.candidate_payload(candidate_id)
    changed_payload["definition_en"] = "a deliberately unrelated but valid meaning"
    repository.create_revision(
        str(original_revision_id),
        changed_payload,
        "fixture-reviewer",
        "Changed definition without new source evidence",
    )

    pack = VerifiedLexicalPackComposer(graph_catalog.store).compose(
        seeded["validation_run_id"], "v1"
    )

    assert pack.senses[0]["definition_en"] == "a set of written pages"


def test_verified_pack_rejects_a_candidate_mapped_from_another_raw_input(
    graph_catalog,
):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)
    candidates = _input_candidates(graph_catalog.store, seeded["validation_run_id"])
    approved_input_id = seeded["approved_input_ids"][0]
    rejected_input_id = seeded["rejected_input_id"]
    approved_candidate_id = candidates[approved_input_id]
    approved_canonical_key = graph_catalog.store.fetch_value(
        "SELECT canonical_key FROM lexical_input_canonical_map WHERE input_id = ?",
        [approved_input_id],
    )
    assert approved_canonical_key is not None
    graph_catalog.store.connection().execute(
        """
        UPDATE lexical_input_dispositions
        SET state = 'validated', candidate_id = ?
        WHERE validation_run_id = ? AND input_id = ?
        """,
        [approved_candidate_id, seeded["validation_run_id"], rejected_input_id],
    )
    graph_catalog.store.connection().execute(
        """
        UPDATE lexical_input_canonical_map
        SET canonical_key = ?, candidate_id = ?
        WHERE input_id = ?
        """,
        [approved_canonical_key, approved_candidate_id, rejected_input_id],
    )

    with pytest.raises(ValueError, match="candidate raw record does not match"):
        VerifiedLexicalPackComposer(graph_catalog.store).compose(
            seeded["validation_run_id"], "v1"
        )

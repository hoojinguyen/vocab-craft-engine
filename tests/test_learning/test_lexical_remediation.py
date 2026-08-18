from __future__ import annotations

import pytest

from src.learning.lexical_evidence import LexicalEvidenceRepository
from src.learning.lexical_remediation import LexicalRemediationService
from tests.test_learning.test_lexical_evidence import _append_input, _snapshot


def test_remediation_validates_and_quarantines_without_approval(
    graph_catalog,
):
    snapshot_id = _snapshot(graph_catalog)
    validated_input = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:valid",
        word_id=10,
        definition_id=1,
        examples=[
            {
                "id": 10,
                "source_row_id": 10,
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    )
    quarantined_input = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:bad",
        word_id=11,
        definition_id=2,
        examples=[
            {
                "id": 11,
                "source_row_id": 11,
                "text_en": "Read it before class.",
                "text_vi": "Hãy đọc nó trước giờ học.",
                "source": "tatoeba",
            }
        ],
    )

    report = LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="run-1"
    )

    assert report.processed_count == 2
    assert report.validated_count == 1
    assert report.quarantined_count == 1
    assert (
        graph_catalog.store.connection()
        .execute(
            """
            SELECT input_id, state FROM lexical_input_dispositions
            WHERE validation_run_id = ? ORDER BY input_id
            """,
            ["run-1"],
        )
        .fetchall()
        == sorted([(validated_input, "validated"), (quarantined_input, "quarantined")])
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM content_candidates WHERE state = 'approved'"
        )
        == 0
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_quarantine_cases WHERE status = 'open'"
        )
        == 1
    )
    raw_count = graph_catalog.store.fetch_value(
        "SELECT count(*) FROM raw_reference_records"
    )
    attempt_count = graph_catalog.store.fetch_value(
        "SELECT count(*) FROM lexical_remediation_attempts"
    )

    rerun = LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="run-1"
    )

    assert rerun == report
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records")
        == raw_count
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_remediation_attempts"
        )
        == attempt_count
    )


def test_completed_and_resumed_runs_have_same_selection_disposition_and_candidate_counts(
    graph_catalog,
):
    snapshot_id = _snapshot(graph_catalog)
    for index, example in enumerate(
        ("Read this book.", "Read that book.", "Read another book."), start=1
    ):
        _append_input(
            graph_catalog,
            snapshot_id,
            external_key=f"resume:{index}",
            word_id=index,
            definition_id=index,
            examples=[
                {
                    "id": index,
                    "source_row_id": index,
                    "text_en": example,
                    "text_vi": "Hãy đọc quyển sách này.",
                    "source": "tatoeba",
                }
            ],
        )

    service = LexicalRemediationService(graph_catalog.store)
    with pytest.raises(RuntimeError, match="interrupted"):
        service.run("lexical-snapshot", validation_run_id="resumed", interrupt_after=1)
    resumed = service.run("lexical-snapshot", validation_run_id="resumed")
    completed = service.run("lexical-snapshot", validation_run_id="complete")

    repository = LexicalEvidenceRepository(graph_catalog.store)
    assert resumed.processed_count == completed.processed_count == 3
    assert repository.selection_signature("resumed") == repository.selection_signature(
        "complete"
    )
    assert repository.disposition_counts("resumed") == repository.disposition_counts(
        "complete"
    )
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM content_candidates") == 3
    )
    assert (
        graph_catalog.store.fetch_value(
            """
        SELECT completed_at IS NOT NULL FROM lexical_run_checkpoints
        WHERE validation_run_id = ? AND phase = 'remediation'
        """,
            ["resumed"],
        )
        is True
    )


def test_duplicate_inputs_map_to_one_canonical_key_and_retry_keeps_alternatives(
    graph_catalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_ids = [
        _append_input(
            graph_catalog,
            snapshot_id,
            external_key=f"duplicate:{index}",
            word_id=index,
            definition_id=index,
            examples=[
                {
                    "id": index,
                    "source_row_id": index,
                    "text_en": "Read it before class.",
                    "text_vi": "Hãy đọc nó trước giờ học.",
                    "source": "tatoeba",
                }
            ],
        )
        for index in (10, 11)
    ]
    service = LexicalRemediationService(graph_catalog.store)
    service.run(snapshot_id, validation_run_id="run-1")

    mappings = (
        graph_catalog.store.connection()
        .execute(
            """
        SELECT input_id, canonical_key FROM lexical_input_canonical_map
        WHERE input_id IN (?, ?) ORDER BY input_id
        """,
            input_ids,
        )
        .fetchall()
    )
    assert {row[0] for row in mappings} == set(input_ids)
    assert len({row[1] for row in mappings}) == 1
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_remediation_attempts WHERE input_id = ?",
            [input_ids[0]],
        )
        == 1
    )

    retry = service.retry_input("run-1", input_ids[0])

    assert retry.state.value == "quarantined"
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_remediation_attempts WHERE input_id = ?",
            [input_ids[0]],
        )
        == 2
    )
    alternatives = graph_catalog.store.fetch_value(
        "SELECT alternatives_json FROM lexical_quarantine_cases WHERE input_id = ?",
        [input_ids[0]],
    )
    assert '"evidence_id"' in str(alternatives)

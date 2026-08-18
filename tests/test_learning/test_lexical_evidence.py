from __future__ import annotations

import json

import pytest

from src.learning.catalog import RawRecordInput, SourceCatalog, SourceEvidenceLinkInput
from src.learning.lexical_evidence import (
    LexicalEvidenceRepository,
    LexicalEvidenceSelector,
)
from src.learning.lexical_remediation import LexicalRemediationService
from src.learning.models import EvidenceRanking, EvidenceRole
from src.learning.quality import QualityGate


def _snapshot(catalog: SourceCatalog) -> str:
    with catalog.store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_snapshots (
                snapshot_id, asset_id, local_path, retrieved_at, file_sha256
            ) VALUES (?, ?, ?, current_timestamp, ?)
            """,
            ["lexical-snapshot", "human-authored-a0", "/tmp/lexical.db", "a" * 64],
        )
    return "lexical-snapshot"


def _append_input(
    catalog: SourceCatalog,
    snapshot_id: str,
    *,
    external_key: str,
    word_id: int,
    definition_id: int,
    lemma: str = "book",
    pos: str = "noun",
    definition_en: str = "a set of written pages",
    definition_vi: str | None = "quyển sách",
    ipa: str | None = "/bʊk/",
    examples: list[dict[str, object]] | None = None,
    translations: list[dict[str, object]] | None = None,
    definitions: list[dict[str, object]] | None = None,
) -> str:
    definition = {
        "id": definition_id,
        "source_row_id": definition_id,
        "definition_id": definition_id,
        "definition_en": definition_en,
        "definition_vi": definition_vi,
        "source": "kaikki",
    }
    record = RawRecordInput(
        asset_id="human-authored-a0",
        external_key=external_key,
        record_type="sqlite_lexical_definition_evidence",
        import_run_id="evidence-test",
        payload={
            "word": {
                "id": word_id,
                "source_row_id": word_id,
                "lemma": lemma,
                "pos": pos,
                "frequency_rank": 100,
                "ipa_uk": ipa,
                "ipa_us": ipa,
                "source": "kaikki",
            },
            "definition": definition,
            "definitions": definitions if definitions is not None else [definition],
            "translations": (
                translations
                if translations is not None
                else (
                    []
                    if definition_vi is None
                    else [
                        {
                            "source_row_id": definition_id,
                            "definition_id": definition_id,
                            "text": definition_vi,
                            "source": "kaikki",
                        }
                    ]
                )
            ),
            "examples": examples or [],
        },
    )
    catalog.append_lexical_definition_record(record, snapshot_id)
    input_id = catalog.store.fetch_value(
        "SELECT input_id FROM lexical_definition_inputs WHERE input_key = ?",
        [f"human-authored-a0:{snapshot_id}:{external_key}"],
    )
    assert input_id is not None
    return str(input_id)


def test_selector_prefers_definition_level_inflected_example_and_persists_all_rankings(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:1",
        word_id=10,
        definition_id=1,
        examples=[
            {
                "id": 10,
                "source_row_id": 10,
                "kind": "linked",
                "text_en": "Those books are heavy.",
                "text_vi": "Những quyển sách đó nặng.",
                "link_rank": 9,
                "source": "tatoeba",
            },
            {
                "id": 20,
                "source_row_id": 20,
                "kind": "definition",
                "text_en": "These books are expensive.",
                "text_vi": "Những quyển sách này đắt.",
                "link_rank": 99,
                "source": "kaikki",
            },
        ],
    )
    repository = LexicalEvidenceRepository(graph_catalog.store)
    selection = LexicalEvidenceSelector().select(repository.get_input(input_id))

    selected_examples = [
        item
        for item in selection.items
        if item.evidence.evidence_role.value == "example" and item.selected
    ]
    assert len(selected_examples) == 1
    assert selected_examples[0].evidence.source_row_id == 20
    assert selected_examples[0].reason["lemma_match"] == "inflection"
    assert selection.failure_codes == ()

    repository.create_validation_run(
        "run-1", snapshot_id, "evidence-test-v1", {"scope": "single-input"}
    )
    repository.upsert_rankings("run-1", selection.rankings("run-1"))
    rankings = (
        graph_catalog.store.connection()
        .execute(
            """
        SELECT selected, eligible, reason_json
        FROM lexical_evidence_rankings
        WHERE validation_run_id = ? AND input_id = ?
        ORDER BY evidence_id
        """,
            ["run-1", input_id],
        )
        .fetchall()
    )
    evidence_count = graph_catalog.store.fetch_value(
        "SELECT count(*) FROM lexical_evidence_items WHERE input_id = ?", [input_id]
    )
    assert len(rankings) == evidence_count
    # Definition, translation, two independently sourced IPA variants, and one
    # example are selected; the weak linked example remains auditable but unused.
    assert sum(bool(row[0]) for row in rankings) == 5
    assert all(json.loads(str(row[2]))["source_row_id"] > 0 for row in rankings)


def test_inputs_share_complete_normalized_word_example_inventory(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    first_input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:1",
        word_id=10,
        definition_id=1,
    )
    second_input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:2",
        word_id=10,
        definition_id=2,
        definition_en="a written work",
    )
    graph_catalog.append_source_example_links(
        [
            SourceEvidenceLinkInput(
                snapshot_id=snapshot_id,
                source_word_id=10,
                source_row_id=sentence_id,
                source_name="tatoeba",
                source_table="sentences",
                link_rank=rank,
                value={
                    "kind": "linked",
                    "sentence_id": sentence_id,
                    "text_en": f"That book example {rank} is useful.",
                    "text_vi": f"Ví dụ sách {rank} hữu ích.",
                    "source": "tatoeba",
                },
            )
            for rank, sentence_id in enumerate((10, 20, 30, 40, 50), start=1)
        ]
    )

    repository = LexicalEvidenceRepository(graph_catalog.store)
    first_examples = [
        item
        for item in repository.get_input(first_input_id).evidence
        if item.evidence_role.value == "example"
    ]
    second_examples = [
        item
        for item in repository.get_input(second_input_id).evidence
        if item.evidence_role.value == "example"
    ]

    assert [item.source_row_id for item in first_examples] == [10, 20, 30, 40, 50]
    assert [item.source_row_id for item in second_examples] == [10, 20, 30, 40, 50]
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM lexical_source_evidence")
        == 5
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_word_evidence_links"
        )
        == 5
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_evidence_items WHERE evidence_role = 'example'"
        )
        == 0
    )
    selection = LexicalEvidenceSelector().select(repository.get_input(first_input_id))
    alternatives = selection.alternatives()
    source_inventory = [
        alternative
        for alternative in alternatives
        if alternative.get("inventory") == "lexical_word_evidence_links"
    ]
    assert len(source_inventory) == 1
    assert source_inventory[0]["evidence_role"] == "example"
    assert source_inventory[0]["source_word_id"] == 10
    assert source_inventory[0]["alternative_count"] == 4
    assert len(source_inventory[0]["fingerprint"]) == 64


def test_virtual_examples_preserve_word_sentence_link_rank(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:rank",
        word_id=10,
        definition_id=1,
    )
    graph_catalog.append_source_example_links(
        [
            SourceEvidenceLinkInput(
                snapshot_id=snapshot_id,
                source_word_id=10,
                source_row_id=10,
                source_name="tatoeba",
                source_table="sentences",
                link_rank=2,
                value={
                    "kind": "linked",
                    "sentence_id": 10,
                    "text_en": "This book is less preferred.",
                    "text_vi": "Cuốn sách này ít được ưu tiên hơn.",
                    "source": "tatoeba",
                },
            ),
            SourceEvidenceLinkInput(
                snapshot_id=snapshot_id,
                source_word_id=10,
                source_row_id=20,
                source_name="tatoeba",
                source_table="sentences",
                link_rank=1,
                value={
                    "kind": "linked",
                    "sentence_id": 20,
                    "text_en": "This book is preferred.",
                    "text_vi": "Cuốn sách này được ưu tiên.",
                    "source": "tatoeba",
                },
            ),
        ]
    )

    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )

    selected = selection.selected_by_role(EvidenceRole.EXAMPLE)
    assert [item.evidence.source_row_id for item in selected] == [20]
    assert selected[0].reason["verified_provenance"] is True


def test_source_ranking_rejects_evidence_not_linked_to_its_input_word(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:unlinked",
        word_id=99,
        definition_id=1,
    )
    source_evidence_id = graph_catalog.append_source_example_links(
        [
            SourceEvidenceLinkInput(
                snapshot_id=snapshot_id,
                source_word_id=10,
                source_row_id=10,
                source_name="tatoeba",
                source_table="sentences",
                link_rank=1,
                value={
                    "kind": "linked",
                    "sentence_id": 10,
                    "text_en": "This book is unrelated.",
                    "text_vi": "Cuốn sách này không liên quan.",
                    "source": "tatoeba",
                },
            )
        ]
    )[0]
    repository = LexicalEvidenceRepository(graph_catalog.store)
    repository.create_validation_run("cross-link-run", snapshot_id, "v1", {})

    with pytest.raises(ValueError, match="not linked to lexical input"):
        repository.upsert_source_rankings(
            "cross-link-run",
            [
                EvidenceRanking(
                    validation_run_id="cross-link-run",
                    input_id=input_id,
                    evidence_id=source_evidence_id,
                    evidence_role=EvidenceRole.EXAMPLE,
                    rank=1,
                    selected=True,
                    eligible=True,
                    reason={},
                )
            ],
        )


def test_remediation_persists_only_selected_normalized_example_rankings(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="book:1",
        word_id=10,
        definition_id=1,
    )
    graph_catalog.append_source_example_links(
        [
            SourceEvidenceLinkInput(
                snapshot_id=snapshot_id,
                source_word_id=10,
                source_row_id=sentence_id,
                source_name="tatoeba",
                source_table="sentences",
                link_rank=rank,
                value={
                    "kind": "linked",
                    "sentence_id": sentence_id,
                    "text_en": f"This book example {rank} is useful.",
                    "text_vi": f"Ví dụ sách {rank} hữu ích.",
                    "source": "tatoeba",
                },
            )
            for rank, sentence_id in enumerate((10, 20, 30, 40, 50), start=1)
        ]
    )

    report = LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="normalized-example-run"
    )

    assert report.processed_count == 1
    assert (
        graph_catalog.store.fetch_value(
            """
            SELECT count(*) FROM lexical_source_evidence_rankings
            WHERE validation_run_id = ? AND evidence_role = 'example'
            """,
            ["normalized-example-run"],
        )
        == 1
    )
    rationale_json = graph_catalog.store.fetch_value(
        """
        SELECT rationale_json FROM lexical_input_dispositions
        WHERE validation_run_id = ?
        """,
        ["normalized-example-run"],
    )
    rationale = json.loads(str(rationale_json))
    inventory = rationale["source_evidence_inventory"]["example"]
    assert inventory["count"] == 5
    assert len(inventory["fingerprint"]) == 64
    attempt_json = graph_catalog.store.fetch_value(
        """
        SELECT selection_json FROM lexical_remediation_attempts
        WHERE validation_run_id = ?
        """,
        ["normalized-example-run"],
    )
    assert "ranked_evidence_ids" not in str(attempt_json)


@pytest.mark.parametrize(
    ("lemma", "pos", "definition_en", "example", "expected_code"),
    [
        (
            "do",
            "verb",
            "perform an action",
            "I do not know the answer.",
            "example.pos_or_form_mismatch",
        ),
        (
            "word",
            "verb",
            "express something in words",
            "I learned a new word today.",
            "example.pos_or_form_mismatch",
        ),
        (
            "yet",
            "adv",
            "until the present time",
            "Yet the train left on time.",
            "example.sense_unproven",
        ),
        (
            "book",
            "noun",
            "a set of written pages",
            "Read it before class.",
            "example.lemma_missing",
        ),
    ],
)
def test_source_evidence_policy_quarantines_semantically_unproven_examples(
    graph_catalog: SourceCatalog,
    lemma: str,
    pos: str,
    definition_en: str,
    example: str,
    expected_code: str,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key=f"pilot:{lemma}",
        word_id=10,
        definition_id=1,
        lemma=lemma,
        pos=pos,
        definition_en=definition_en,
        examples=[
            {
                "id": 10,
                "source_row_id": 10,
                "text_en": example,
                "text_vi": "Bản dịch ví dụ hợp lệ.",
                "source": "tatoeba",
            }
        ],
    )
    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )
    report = QualityGate().validate_lexical_source_evidence(selection)

    assert expected_code in {failure.code for failure in report.failures}
    assert report.passed is False


@pytest.mark.parametrize(
    ("lemma", "pos", "definition_en", "example", "expected_code"),
    [
        (
            "do",
            "verb",
            "perform an action",
            "I do not know the answer.",
            "example.pos_or_form_mismatch",
        ),
        (
            "word",
            "verb",
            "express something in words",
            "I learned a new word today.",
            "example.pos_or_form_mismatch",
        ),
        (
            "yet",
            "adv",
            "until the present time",
            "Yet the train left on time.",
            "example.sense_unproven",
        ),
        (
            "book",
            "noun",
            "a set of written pages",
            "Read it before class.",
            "example.lemma_missing",
        ),
    ],
)
def test_semantic_gate_rejects_pilot_cases_after_legacy_structural_gate_passes(
    graph_catalog: SourceCatalog,
    lemma: str,
    pos: str,
    definition_en: str,
    example: str,
    expected_code: str,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key=f"pilot:{lemma}:structural-pass",
        word_id=10,
        definition_id=1,
        lemma=lemma,
        pos=pos,
        definition_en=definition_en,
        examples=[
            {
                "id": 10,
                "source_row_id": 10,
                "text_en": example,
                "text_vi": "Tôi không biết câu trả lời.",
                "source": "tatoeba",
            }
        ],
    )
    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )
    payload = LexicalRemediationService._candidate_payload(selection)
    payload["examples"] = [
        {
            "text_en": example,
            "text_vi": "Tôi không biết câu trả lời.",
            "source": "tatoeba",
        }
    ]

    assert QualityGate().validate_payload("sense", payload).passed is True
    assert expected_code in selection.failure_codes


def test_source_evidence_gate_reports_missing_translation_ipa_and_conflicting_metadata(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="conflict:book",
        word_id=10,
        definition_id=1,
        definition_vi=None,
        ipa=None,
        definitions=[
            {
                "id": 1,
                "source_row_id": 1,
                "definition_id": 1,
                "definition_en": "a set of written pages",
                "definition_vi": None,
                "pos": "verb",
                "source": "kaikki",
            }
        ],
        translations=[
            {
                "source_row_id": 1,
                "definition_id": 1,
                "text": "quyển sách",
                "pos": "noun",
                "source": "kaikki",
            },
            {
                "source_row_id": 2,
                "definition_id": 1,
                "text": "đặt chỗ",
                "pos": "verb",
                "source": "kaikki",
            },
        ],
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
    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )
    codes = {
        failure.code
        for failure in QualityGate()
        .validate_lexical_source_evidence(selection)
        .failures
    }

    assert {
        "ipa.missing_or_unverified",
        "source_evidence_conflict",
    } <= codes


def test_source_evidence_gate_distinguishes_unknown_translation_quality(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="unknown-translation:book",
        word_id=10,
        definition_id=1,
        translations=[
            {
                "source_row_id": 1,
                "definition_id": 1,
                "text": "quyển sách",
                "source": "unspecified-legacy-source",
            }
        ],
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

    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )
    codes = {
        failure.code
        for failure in QualityGate()
        .validate_lexical_source_evidence(selection)
        .failures
    }

    assert "translation.quality_unknown" in codes
    assert "translation.missing_or_invalid" not in codes


def test_source_evidence_gate_reports_missing_or_invalid_translation(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="missing-translation:book",
        word_id=10,
        definition_id=1,
        definition_vi=None,
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

    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )

    assert "translation.missing_or_invalid" in selection.failure_codes


def test_source_evidence_gate_reports_incomplete_provenance(
    graph_catalog: SourceCatalog,
):
    snapshot_id = _snapshot(graph_catalog)
    input_id = _append_input(
        graph_catalog,
        snapshot_id,
        external_key="incomplete-provenance:book",
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
    graph_catalog.store.connection().execute(
        "UPDATE lexical_evidence_items SET source_name = 'untrusted-source' WHERE input_id = ?",
        [input_id],
    )

    selection = LexicalEvidenceSelector().select(
        LexicalEvidenceRepository(graph_catalog.store).get_input(input_id)
    )

    assert "provenance.incomplete" in selection.failure_codes

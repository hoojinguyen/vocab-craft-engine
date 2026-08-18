from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.learning.models import (
    CandidateState,
    ContentRevisionInput,
    ContentType,
    EvidenceItem,
    EvidenceRanking,
    InputDisposition,
    LexicalDefinitionInput,
    RemediationAttempt,
    RemediationRunReport,
    ReviewState,
    SourceAssetInput,
    SourceSnapshotInput,
)


def test_candidate_state_is_separate_from_review_state():
    assert tuple(CandidateState) == (
        CandidateState.CANDIDATE,
        CandidateState.VALIDATED,
        CandidateState.APPROVED,
        CandidateState.REJECTED,
        CandidateState.QUARANTINED,
    )
    assert "validated" not in {state.value for state in ReviewState}


def test_source_snapshot_input_validates_immutable_provenance_fields():
    retrieved_at = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
    source_snapshot = SourceSnapshotInput(
        asset_id="fixture-source",
        local_path=Path("data/raw/reference.db"),
        retrieved_at=retrieved_at,
        file_sha256="a" * 64,
    )

    assert source_snapshot.local_path == Path("data/raw/reference.db")
    assert source_snapshot.retrieved_at == retrieved_at

    with pytest.raises(ValidationError):
        source_snapshot.file_sha256 = "A" * 64

    with pytest.raises(ValidationError):
        SourceSnapshotInput(
            asset_id="NO",
            local_path=Path("data/raw/reference.db"),
            retrieved_at=retrieved_at,
            file_sha256="A" * 64,
        )


def test_source_asset_requires_license_and_attribution_for_approval():
    with pytest.raises(ValidationError, match="license_id"):
        SourceAssetInput(
            asset_id="test-source",
            title="Test source",
            locator="https://example.test/source",
            asset_version="2026-01",
            sha256="a" * 64,
            license_id="",
            license_url="https://example.test/license",
            attribution="",
            redistribution_allowed=True,
            validation_status="approved",
        )


def test_revision_input_has_deterministic_payload_hash():
    first = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": "Greet someone", "code": "A0.GREET"},
    )
    second = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"code": "A0.GREET", "outcome": "Greet someone"},
    )
    assert first.payload_sha256 == second.payload_sha256
    assert ReviewState.APPROVED.value == "approved"


def test_revision_payload_hash_tracks_nested_mutation_and_model_copy():
    revision = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": {"text": "Greet someone"}},
    )
    original_hash = revision.payload_sha256

    revision.payload["outcome"]["text"] = "Greet a neighbor"
    assert revision.payload_sha256 != original_hash

    copied = revision.model_copy(
        update={"payload": {"outcome": {"text": "Greet a colleague"}}}
    )
    assert copied.payload_sha256 != revision.payload_sha256


def test_revision_payload_hash_is_read_only():
    revision = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": "Greet someone"},
    )

    with pytest.raises((AttributeError, TypeError, ValidationError)):
        revision.payload_sha256 = "0" * 64


def test_approved_source_rejects_blank_license_on_assignment():
    source = SourceAssetInput(
        asset_id="test-source",
        title="Test source",
        locator="https://example.test/source",
        asset_version="2026-01",
        sha256="a" * 64,
        license_id="CC-BY-4.0",
        license_url="https://example.test/license",
        attribution="Test author",
        redistribution_allowed=True,
        validation_status="approved",
    )

    with pytest.raises(ValidationError, match="license_id"):
        source.license_id = ""

    assert source.license_id == "CC-BY-4.0"
    assert source.attribution == "Test author"
    assert source.redistribution_allowed is True
    assert source.validation_status is ReviewState.APPROVED


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
        {"value": object()},
        {"value": {1: "non-string key"}},
        {"value": ("tuple is not JSON",)},
    ],
)
def test_revision_payload_accepts_only_finite_json_values(payload):
    with pytest.raises(ValidationError):
        ContentRevisionInput(
            stable_key="objective.greet",
            content_type=ContentType.OBJECTIVE,
            payload=payload,
        )


def test_lexical_evidence_models_are_frozen_and_canonicalize_json_values():
    created_at = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    lexical_input = LexicalDefinitionInput(
        input_id="input-1",
        snapshot_id="snapshot-1",
        raw_record_id="raw-1",
        source_word_id=10,
        source_definition_id=11,
        input_key="lexical.book.noun.11",
        source_definition_sha256="a" * 64,
        lemma="book",
        pos="noun",
        frequency_rank=42,
        created_at=created_at,
    )
    evidence = EvidenceItem(
        evidence_id="evidence-1",
        input_id=lexical_input.input_id,
        evidence_role="definition",
        source_row_id=11,
        source_name="reference.db",
        value={"text": "a set of pages", "lang": "en"},
        created_at=created_at,
    )
    ranking = EvidenceRanking(
        validation_run_id="run-1",
        input_id=lexical_input.input_id,
        evidence_id=evidence.evidence_id,
        evidence_role="definition",
        rank=1,
        selected=True,
        eligible=True,
        reason={"score": 1.0},
    )
    disposition = InputDisposition(
        validation_run_id="run-1",
        input_id=lexical_input.input_id,
        state="quarantined",
        candidate_id=None,
        failure_codes=["missing_translation"],
        rationale={"source": "gate.translation"},
        updated_at=created_at,
    )
    attempt = RemediationAttempt(
        attempt_id="attempt-1",
        validation_run_id="run-1",
        input_id=lexical_input.input_id,
        attempt_number=1,
        selection={"definition": evidence.evidence_id},
        outcome="validated",
        failure_codes=[],
        rationale={"strategy": "highest-ranked"},
        created_at=created_at,
    )
    report = RemediationRunReport(
        validation_run_id="run-1",
        snapshot_id="snapshot-1",
        processed_count=1,
        validated_count=1,
        quarantined_count=0,
        rejected_count=0,
        failure_counts={},
        completed_at=created_at,
    )

    assert evidence.value_json == '{"lang":"en","text":"a set of pages"}'
    assert (
        evidence.value_sha256
        == "2f82c361cc7b4eda30f49f0aa4dba348f3b16d5d9d11dbab2f999727542e4f07"
    )
    assert ranking.reason_json == '{"score":1.0}'
    assert disposition.failure_codes_json == '["missing_translation"]'
    assert attempt.selection_json == '{"definition":"evidence-1"}'
    assert report.failure_counts_json == "{}"
    with pytest.raises(ValidationError):
        lexical_input.lemma = "novel"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LexicalDefinitionInput(
            input_id="input-1",
            snapshot_id="snapshot-1",
            raw_record_id="raw-1",
            source_word_id=10,
            source_definition_id=11,
            input_key="lexical.book.noun.11",
            source_definition_sha256="A" * 64,
            lemma="book",
            pos="noun",
            frequency_rank=42,
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
        lambda: EvidenceItem(
            evidence_id="evidence-1",
            input_id="input-1",
            evidence_role="definition",
            source_row_id=11,
            source_name="reference.db",
            value={"not": object()},
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
        lambda: EvidenceRanking(
            validation_run_id="run-1",
            input_id="input-1",
            evidence_id="evidence-1",
            evidence_role="audio",
            rank=1,
            selected=True,
            eligible=True,
            reason={},
        ),
        lambda: InputDisposition(
            validation_run_id="run-1",
            input_id="input-1",
            state="approved",
            candidate_id=None,
            failure_codes=[],
            rationale={},
            updated_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
        lambda: RemediationAttempt(
            attempt_id="attempt-1",
            validation_run_id="run-1",
            input_id="input-1",
            attempt_number=1,
            selection={},
            outcome="approved",
            failure_codes=[],
            rationale={},
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
    ],
)
def test_lexical_evidence_models_reject_invalid_hashes_json_and_approval(factory):
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("source_word_id", None),
        ("source_word_id", 0),
        ("source_word_id", -1),
        ("source_definition_id", None),
        ("source_definition_id", 0),
        ("source_definition_id", -1),
    ],
)
def test_lexical_definition_input_requires_positive_source_identifiers(
    field_name: str, value: int | None
):
    input_values: dict[str, object] = {
        "input_id": "input-1",
        "snapshot_id": "snapshot-1",
        "raw_record_id": "raw-1",
        "source_word_id": 10,
        "source_definition_id": 11,
        "input_key": "lexical.book.noun.11",
        "source_definition_sha256": "a" * 64,
        "lemma": "book",
        "pos": "noun",
        "frequency_rank": 42,
        "created_at": datetime(2026, 8, 18, tzinfo=UTC),
    }
    input_values[field_name] = value

    with pytest.raises(ValidationError):
        LexicalDefinitionInput(**input_values)


@pytest.mark.parametrize("frequency_rank", [0, -1, 3501])
def test_lexical_definition_input_requires_rank_in_frozen_scope(
    frequency_rank: int,
):
    with pytest.raises(ValidationError):
        LexicalDefinitionInput(
            input_id="input-1",
            snapshot_id="snapshot-1",
            raw_record_id="raw-1",
            source_word_id=10,
            source_definition_id=11,
            input_key="lexical.book.noun.11",
            source_definition_sha256="a" * 64,
            lemma="book",
            pos="noun",
            frequency_rank=frequency_rank,
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
        )


@pytest.mark.parametrize("source_row_id", [None, 0, -1])
def test_evidence_item_requires_a_positive_source_row_id(source_row_id: int | None):
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="evidence-1",
            input_id="input-1",
            evidence_role="definition",
            source_row_id=source_row_id,
            source_name="reference.db",
            value={"text": "a set of pages"},
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
        )

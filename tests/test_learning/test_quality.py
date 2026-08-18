import pytest

from src.learning.quality import QualityGate


def test_sentence_requires_reviewed_vi_translation_and_level_evidence():
    report = QualityGate().validate_revision(
        {
            "content_type": "sentence",
            "review_state": "approved",
            "payload": {
                "stable_key": "sentence.hello",
                "text_en": "Hello.",
                "text_vi": "",
                "cefr_level": "A1",
                "cefr_method": "",
                "naturalness_score": 0.9,
                "translation_reviewed": True,
            },
        }
    )

    assert report.passed is False
    assert {failure.code for failure in report.failures} == {
        "sentence.translation_missing",
        "sentence.level_evidence_missing",
    }


def test_branching_scenario_requires_semantic_response_path():
    report = QualityGate().validate_graph(
        revisions=[
            {
                "revision_id": "scenario",
                "content_type": "scenario",
                "review_state": "approved",
                "payload": {
                    "stable_key": "scenario.shop",
                    "goal": "Buy water",
                    "roles": ["learner", "clerk"],
                    "register": "neutral",
                    "end_condition": "purchase complete",
                    "practice_mode": "branching",
                },
            },
            {
                "revision_id": "turn-1",
                "content_type": "dialogue_turn",
                "review_state": "approved",
                "payload": {
                    "stable_key": "turn.1",
                    "text_en": "Hello",
                    "text_vi": "Xin chào",
                    "speaker_role": "learner",
                },
            },
        ],
        edges=[
            {
                "from_revision_id": "scenario",
                "to_revision_id": "turn-1",
                "relation_type": "scenario_turn",
                "attributes": {},
            }
        ],
    )

    assert "scenario.branch_missing" in {failure.code for failure in report.failures}


def test_ipa_claim_needs_confidence_and_source_not_copied_variant():
    report = QualityGate().validate_revision(
        {
            "content_type": "lexeme",
            "review_state": "approved",
            "payload": {
                "stable_key": "lexeme.hello",
                "lemma": "hello",
                "ipa_us": "/həˈloʊ/",
                "ipa_uk": "/həˈloʊ/",
                "ipa_source": "generated",
                "ipa_confidence": 0.2,
            },
        }
    )

    assert "lexeme.ipa_unverified" in {failure.code for failure in report.failures}


def test_quality_summary_reports_review_state_source_and_cefr_counts():
    summary = QualityGate().summarize(
        [
            {
                "content_type": "objective",
                "review_state": "approved",
                "source_asset_id": "human-authored-a0",
                "payload": {"cefr_level": "A1"},
            },
            {
                "content_type": "sentence",
                "review_state": "quarantined",
                "source_asset_id": "legacy",
                "payload": {"cefr_level": "B2"},
            },
        ]
    )

    assert summary["review_states"] == {"approved": 1, "quarantined": 1}
    assert summary["source_assets"] == {"human-authored-a0": 1, "legacy": 1}
    assert summary["cefr_levels"] == {"A1": 1, "B2": 1}


def _valid_sense_payload() -> dict[str, object]:
    return {
        "stable_key": "sense.book.noun.123456789abc",
        "lemma": "book",
        "pos": "noun",
        "frequency_rank": 100,
        "cefr_level": "A1",
        "cefr_method": "frequency_rank_v1",
        "definition_en": "a set of pages",
        "definition_vi": "quyển sách",
        "ipa_uk": "/bʊk/",
        "ipa_us": "/bʊk/",
        "ipa_source": "kaikki",
        "ipa_confidence": 0.8,
        "examples": [
            {
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    }


def test_sense_gate_rejects_passthrough_translation_and_missing_ipa():
    payload = _valid_sense_payload() | {
        "definition_vi": "a set of pages",
        "ipa_uk": None,
        "ipa_us": None,
        "ipa_source": None,
    }

    report = QualityGate().validate_payload("sense", payload, "candidate-1")

    assert {failure.code for failure in report.failures} == {
        "sense.translation_passthrough",
        "sense.ipa_missing",
    }
    assert {failure.revision_id for failure in report.failures} == {"candidate-1"}


@pytest.mark.parametrize(
    ("changes", "gate_code"),
    [
        ({"lemma": "book name"}, "sense.lemma_invalid"),
        ({"pos": "particle"}, "sense.pos_invalid"),
        ({"frequency_rank": 3501}, "sense.frequency_rank_invalid"),
        ({"cefr_level": "A2"}, "sense.cefr_mismatch"),
        ({"definition_en": " "}, "sense.definition_missing"),
        ({"definition_vi": " "}, "sense.translation_missing"),
        ({"definition_vi": "[VI] book"}, "sense.translation_placeholder"),
        (
            {"definition_vi": " A  SET\tof   PAGES "},
            "sense.translation_passthrough",
        ),
        (
            {"ipa_uk": None, "ipa_us": None, "ipa_source": None},
            "sense.ipa_missing",
        ),
        ({"ipa_confidence": 0.79}, "sense.ipa_unverified"),
        ({"examples": []}, "sense.example_missing"),
        (
            {
                "examples": [
                    {"text_en": "same", "text_vi": " SAME ", "source": "fixture"}
                ]
            },
            "sense.example_alignment_invalid",
        ),
    ],
)
def test_sense_gate_uses_the_declared_stable_failure_codes(
    changes: dict[str, object], gate_code: str
):
    report = QualityGate().validate_payload("sense", _valid_sense_payload() | changes)

    assert {failure.code for failure in report.failures} == {gate_code}


def test_validate_revision_delegates_sense_payload_validation_with_revision_id():
    report = QualityGate().validate_revision(
        {
            "revision_id": "revision-1",
            "content_type": "sense",
            "review_state": "candidate",
            "payload": _valid_sense_payload() | {"examples": []},
        }
    )

    assert {failure.code for failure in report.failures} == {
        "revision.not_approved",
        "sense.example_missing",
    }
    assert {failure.revision_id for failure in report.failures} == {"revision-1"}

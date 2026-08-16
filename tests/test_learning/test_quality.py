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

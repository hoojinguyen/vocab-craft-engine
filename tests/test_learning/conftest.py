from dataclasses import replace
from pathlib import Path

import pytest

from src.learning.catalog import SourceCatalog
from src.learning.composer import CurriculumComposer
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.repository import ContentRepository
from src.learning.store import LearningGraphStore


@pytest.fixture
def graph_catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    catalog = SourceCatalog(store)
    catalog.register_source(
        SourceAssetInput(
            asset_id="human-authored-a0",
            title="Human-authored A0 pilot content",
            locator="https://example.test/a0",
            asset_version="2026-08",
            sha256="a" * 64,
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Vocab Craft editorial team",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    return catalog


class GraphRepositoryFixture:
    def __init__(self, catalog: SourceCatalog):
        self.catalog = catalog
        self.repository = ContentRepository(catalog.store)

    def add_edge(self, *args, **kwargs):
        return self.repository.add_edge(*args, **kwargs)

    def _approved_revision(self, content_type: str, payload: dict, key: str) -> str:
        raw_id = self.catalog.record_raw_snapshot(
            "human-authored-a0", f"seed:{key}", {"key": key}
        )
        candidate_id = self.repository.create_candidate(
            raw_id, content_type, payload, {"source": "fixture"}, 1.0
        )
        self.repository.mark_candidate_validated(candidate_id)
        revision_id = self.repository.review_candidate(
            candidate_id, "approved", "fixture-editor", "Approved fixture content"
        )
        assert revision_id is not None
        return revision_id

    def seed_minimum_valid_module(
        self, *, include_scenario: bool = True, include_activity: bool = True
    ) -> tuple[str, str, str]:
        module = self._approved_revision(
            "module",
            {
                "stable_key": "module.a0.greetings",
                "code": "A0.GREETINGS",
                "title": "Greetings",
                "cefr_level": "A0",
            },
            "module",
        )
        objective = self._approved_revision(
            "objective",
            {
                "stable_key": "objective.a0.greet",
                "code": "A0.GREET",
                "outcome": "Greet another person",
                "success_criteria": ["Uses a greeting"],
                "cefr_level": "A0",
                "cefr_method": "editorial-calibration",
            },
            "objective",
        )
        prerequisite = self._approved_revision(
            "sense",
            {
                "stable_key": "sense.hello.noun.123456789abc",
                "lemma": "hello",
                "pos": "noun",
                "frequency_rank": 100,
                "cefr_level": "A1",
                "cefr_method": "frequency_rank_v1",
                "definition_en": "an expression of greeting",
                "definition_vi": "một lời chào",
                "ipa_uk": "/həˈləʊ/",
                "ipa_us": "/həˈloʊ/",
                "ipa_source": "kaikki",
                "ipa_confidence": 0.8,
                "examples": [
                    {
                        "text_en": "Say hello to your friend.",
                        "text_vi": "Hãy chào bạn của bạn.",
                        "source": "fixture",
                    }
                ],
            },
            "prerequisite",
        )
        sentence = self._approved_revision(
            "sentence",
            {
                "stable_key": "sentence.hello",
                "text_en": "Hello!",
                "text_vi": "Xin chào!",
                "cefr_level": "A0",
                "cefr_method": "editorial-calibration",
                "naturalness_score": 1.0,
                "translation_reviewed": True,
            },
            "sentence",
        )
        scenario = self._approved_revision(
            "scenario",
            {
                "stable_key": "scenario.greeting",
                "goal": "Start a friendly conversation",
                "roles": ["learner", "partner"],
                "register": "neutral",
                "end_condition": "greeting exchanged",
                "practice_mode": "linear",
            },
            "scenario",
        )
        turn = self._approved_revision(
            "dialogue_turn",
            {
                "stable_key": "turn.greeting.1",
                "text_en": "Hello!",
                "text_vi": "Xin chào!",
                "speaker_role": "learner",
            },
            "turn",
        )
        template = self._approved_revision(
            "activity_template",
            {
                "stable_key": "template.greeting.free-response",
                "template_key": "greeting.free-response",
                "activity_kind": "free_response",
                "input_contract": {"prompt": "string"},
                "grading_contract": {"mode": "human"},
            },
            "template",
        )
        criterion = self._approved_revision(
            "assessment_criterion",
            {
                "stable_key": "criterion.greeting",
                "criterion_key": "greeting.used",
                "objective_id": "objective.a0.greet",
                "observable_behavior": "Uses an appropriate greeting",
            },
            "criterion",
        )
        activity = self._approved_revision(
            "activity",
            {
                "stable_key": "activity.greeting.free-response",
                "objective_id": "objective.a0.greet",
                "template_id": "template.greeting.free-response",
                "assessment_criterion_id": "criterion.greeting",
                "activity_kind": "free_response",
                "prompt": "Greet your partner.",
                "answer": "Hello!",
            },
            "activity",
        )

        edges = [
            (module, objective, "module_objective"),
            (objective, prerequisite, "prerequisite"),
            (objective, prerequisite, "objective_sense"),
            (objective, sentence, "objective_sentence"),
            (objective, criterion, "objective_assessment"),
        ]
        if include_scenario:
            edges.extend(
                (
                    (objective, scenario, "objective_scenario"),
                    (scenario, turn, "scenario_turn"),
                )
            )
        if include_activity:
            edges.extend(
                (
                    (objective, activity, "objective_activity"),
                    (activity, template, "activity_template"),
                    (activity, criterion, "activity_assessment"),
                )
            )
        for from_id, to_id, relation in edges:
            self.add_edge(from_id, to_id, relation)
        return module, objective, prerequisite


@pytest.fixture
def graph_repository(graph_catalog: SourceCatalog) -> GraphRepositoryFixture:
    return GraphRepositoryFixture(graph_catalog)


@pytest.fixture
def valid_pack_graph(graph_repository: GraphRepositoryFixture):
    module_revision, _, _ = graph_repository.seed_minimum_valid_module()
    return CurriculumComposer(graph_repository.repository).compose(
        module_revision, "a0-a1-pilot", "0.1.0"
    )


@pytest.fixture
def invalid_pack_graph(valid_pack_graph):
    return replace(
        valid_pack_graph,
        quality_report={"passed": False, "failures": [{"code": "test.failed"}]},
    )

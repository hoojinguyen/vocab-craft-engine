import pytest

from src.learning.composer import CurriculumComposer


def test_composer_includes_approved_prerequisites_before_objective(graph_repository):
    module_revision, greeting_revision, prerequisite_revision = (
        graph_repository.seed_minimum_valid_module()
    )

    pack = CurriculumComposer(graph_repository.repository).compose(
        module_revision, "a0-a1-pilot", "0.1.0"
    )

    assert pack.revision_ids.index(prerequisite_revision) < pack.revision_ids.index(
        greeting_revision
    )
    assert pack.revision_ids == tuple(sorted(pack.revision_ids, key=pack.order_key))
    assert pack.quality_report["passed"] is True


def test_composer_rejects_objective_without_scenario_and_assessed_activity(
    graph_repository,
):
    module_revision, _, _ = graph_repository.seed_minimum_valid_module(
        include_scenario=False, include_activity=False
    )

    with pytest.raises(ValueError, match="objective coverage"):
        CurriculumComposer(graph_repository.repository).compose(
            module_revision, "a0-a1-pilot", "0.1.0"
        )

import json

from src.learning.composer import CurriculumComposer
from src.learning.exporter import CurriculumPackExporter


def test_reviewed_a0a1_module_moves_from_source_to_publishable_pack(
    graph_repository, tmp_path
):
    module_revision, _, _ = graph_repository.seed_minimum_valid_module()
    pack = CurriculumComposer(graph_repository.repository).compose(
        module_revision, "a0-a1-pilot", "0.1.0"
    )
    result = CurriculumPackExporter().export(pack, tmp_path / "a0-a1-pilot")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["quality_gates"]["passed"] is True
    assert manifest["source_attributions"][0]["asset_id"] == "human-authored-a0"
    assert len(manifest["revision_ids"]) == len(pack.revisions)

import hashlib
import json
import sqlite3

import pytest

from src.learning.exporter import CurriculumPackExporter


def test_export_writes_immutable_pack_sqlite_json_and_manifest(
    tmp_path, valid_pack_graph
):
    result = CurriculumPackExporter().export(valid_pack_graph, tmp_path / "published")

    assert result.sqlite_path.name == "curriculum.db"
    assert result.json_path.name == "curriculum.json"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["pack_id"] == "a0-a1-pilot"
    assert manifest["version"] == "0.1.0"
    assert manifest["quality_gates"]["passed"] is True
    assert (
        manifest["files"]["curriculum.db"]["sha256"]
        == hashlib.sha256(result.sqlite_path.read_bytes()).hexdigest()
    )
    connection = sqlite3.connect(result.sqlite_path)
    assert connection.execute("SELECT count(*) FROM content_revisions").fetchone()[
        0
    ] == len(valid_pack_graph.revisions)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_export_refuses_failed_pack_before_creating_output(
    tmp_path, invalid_pack_graph
):
    result_dir = tmp_path / "failed"

    with pytest.raises(ValueError, match="quality gates"):
        CurriculumPackExporter().export(invalid_pack_graph, result_dir)

    assert not result_dir.exists()

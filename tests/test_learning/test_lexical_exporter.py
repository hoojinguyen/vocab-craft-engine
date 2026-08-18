from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.learning.lexical_exporter import LexicalPackExporter
from src.learning.lexical_pack import LexicalPackComposer
from src.learning.repository import ContentRepository
from tests.test_learning.test_lexical_pack import _seed_lexical_run


@pytest.fixture
def lexical_pack(graph_catalog):
    validation_run_id = _seed_lexical_run(graph_catalog)
    return LexicalPackComposer(ContentRepository(graph_catalog.store)).compose(
        validation_run_id, "lexical-a1", "0.1.0", "A1"
    )


def test_lexical_export_writes_indexed_offline_artifacts(tmp_path: Path, lexical_pack):
    result = LexicalPackExporter().export(lexical_pack, tmp_path / "lexical-a1")

    assert result.sqlite_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()
    assert result.sha256_path.exists()
    connection = sqlite3.connect(result.sqlite_path)
    try:
        assert connection.execute(
            "SELECT definition_vi FROM senses WHERE lemma = 'lexaa'"
        ).fetchone() == ("nghĩa của lexaa",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM senses WHERE lemma = 'lexaa'"
        ).fetchall()
        assert any("idx_senses_lemma_pos" in str(row) for row in plan)
    finally:
        connection.close()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["pack_id"] == "lexical-a1"
    assert manifest["approved_sense_count"] == 30
    assert {"lexical.db", "lexical.json"}.issubset(manifest["files"])


def test_lexical_export_refuses_to_overwrite_a_published_directory(
    tmp_path: Path, lexical_pack
):
    destination = tmp_path / "lexical-a1"
    LexicalPackExporter().export(lexical_pack, destination)

    with pytest.raises(FileExistsError):
        LexicalPackExporter().export(lexical_pack, destination)

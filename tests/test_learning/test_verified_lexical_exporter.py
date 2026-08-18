from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests.test_learning.test_verified_lexical_pack import seed_resolved_release_graph


def _verified_pack(graph_catalog):
    from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

    seeded = seed_resolved_release_graph(graph_catalog)
    pack = VerifiedLexicalPackComposer(graph_catalog.store).compose(
        seeded["validation_run_id"], "v1"
    )
    return seeded, pack


def test_verified_export_writes_exact_backend_schema_and_manifest(
    graph_catalog, tmp_path: Path
):
    from src.learning.verified_lexical_exporter import VerifiedLexicalPackExporter

    seeded, pack = _verified_pack(graph_catalog)
    result = VerifiedLexicalPackExporter(graph_catalog.store).export(
        pack, tmp_path / "english_dataset_verified_v1"
    )

    assert result.sqlite_path.name == "english_dataset_verified_v1.db"
    assert result.manifest_path.exists()
    assert result.sha256_path.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(result.sqlite_path.read_bytes()).hexdigest()}  "
        "english_dataset_verified_v1.db\n"
    )
    assert result.quarantine_path.exists()
    connection = sqlite3.connect(result.sqlite_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        }
        assert tables == {
            "release_metadata",
            "sense_examples",
            "sense_provenance",
            "senses",
        }
        assert [
            row[1]
            for row in connection.execute("PRAGMA table_info('senses')").fetchall()
        ] == [
            "sense_id",
            "stable_key",
            "lemma",
            "pos",
            "definition_en",
            "definition_vi",
            "ipa_uk",
            "ipa_us",
            "frequency_rank",
            "cefr_level",
        ]
        assert connection.execute("SELECT count(*) FROM senses").fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM sense_provenance"
        ).fetchone() == (2,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('senses')").fetchall()
        }
        assert {"idx_senses_cefr", "idx_senses_lemma_pos", "idx_senses_rank"} <= indexes
    finally:
        connection.close()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation_run_id"] == seeded["validation_run_id"]
    assert manifest["reconciliation"] == pack.reconciliation
    assert manifest["source_attributions"][0]["asset_id"] == "human-authored-a0"
    assert manifest["source_snapshots"][0]["snapshot_id"] == seeded["snapshot_id"]
    assert (
        graph_catalog.store.fetch_value(
            "SELECT manifest_sha256 FROM lexical_release_builds WHERE release_version = 'v1'"
        )
        == hashlib.sha256(result.manifest_path.read_bytes()).hexdigest()
    )


def test_verified_export_is_atomic_and_refuses_an_existing_destination(
    graph_catalog, tmp_path: Path
):
    from src.learning.verified_lexical_exporter import VerifiedLexicalPackExporter

    _, pack = _verified_pack(graph_catalog)
    destination = tmp_path / "english_dataset_verified_v1"
    exporter = VerifiedLexicalPackExporter(graph_catalog.store)
    exporter.export(pack, destination)

    with pytest.raises(FileExistsError):
        exporter.export(pack, destination)


def test_verified_export_never_publishes_when_release_build_recording_fails(
    graph_catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from src.learning.verified_lexical_exporter import VerifiedLexicalPackExporter

    _, pack = _verified_pack(graph_catalog)
    destination = tmp_path / "english_dataset_verified_v1"
    exporter = VerifiedLexicalPackExporter(graph_catalog.store)

    def fail_record(*_args, **_kwargs) -> None:
        raise RuntimeError("release metadata unavailable")

    monkeypatch.setattr(exporter, "_record_release_build", fail_record)

    with pytest.raises(RuntimeError, match="metadata unavailable"):
        exporter.export(pack, destination)

    assert not destination.exists()
    assert not destination.is_symlink()
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM lexical_release_builds WHERE release_version = ?",
            [pack.version],
        )
        == 0
    )


def test_verified_export_refuses_a_dangling_destination_symlink(
    graph_catalog, tmp_path: Path
):
    from src.learning.verified_lexical_exporter import VerifiedLexicalPackExporter

    _, pack = _verified_pack(graph_catalog)
    destination = tmp_path / "english_dataset_verified_v1"
    destination.symlink_to(tmp_path / "not-published")

    with pytest.raises(FileExistsError):
        VerifiedLexicalPackExporter(graph_catalog.store).export(pack, destination)

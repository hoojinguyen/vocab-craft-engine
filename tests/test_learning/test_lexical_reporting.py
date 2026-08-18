from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from src.learning.lexical_remediation import LexicalRemediationService
from src.learning.lexical_reporting import LexicalRunReporter, QuarantineExporter
from tests.test_learning.test_lexical_evidence import _append_input, _snapshot


def _mixed_run(graph_catalog) -> tuple[str, str]:
    snapshot_id = _snapshot(graph_catalog)
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="report:validated",
        word_id=1,
        definition_id=1,
        examples=[
            {
                "id": 1,
                "source_row_id": 1,
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    )
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="report:quarantined",
        word_id=2,
        definition_id=2,
        examples=[
            {
                "id": 2,
                "source_row_id": 2,
                "text_en": "Read it before class.",
                "text_vi": "Hãy đọc nó trước giờ học.",
                "source": "tatoeba",
            }
        ],
    )
    LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="report-run"
    )
    return snapshot_id, "report-run"


def test_reporter_writes_hash_stable_reconciled_report_with_traceable_samples(
    graph_catalog, tmp_path
):
    snapshot_id, run_id = _mixed_run(graph_catalog)
    reporter = LexicalRunReporter(graph_catalog.store)

    first = reporter.write_remediation_report(run_id, tmp_path / "run")
    first_bytes = first.read_bytes()
    second = reporter.write_remediation_report(run_id, tmp_path / "run")

    assert second == first
    assert second.read_bytes() == first_bytes
    report = json.loads(first.read_text(encoding="utf-8"))
    assert report["snapshot_id"] == snapshot_id
    assert report["input_total"] == 2
    assert report["input_total"] == sum(report["counts_by_state"].values())
    assert report["counts_by_state"] == {"quarantined": 1, "validated": 1}
    assert report["counts_by_rank_band"] == {"A1": 2}
    assert report["samples"]["quarantined"][0]["evidence_ids"]
    assert report["samples"]["quarantined"][0]["source_row_ids"]
    assert "text_en" not in report["samples"]["quarantined"][0]


def test_reporter_writes_an_ordered_full_input_manifest(graph_catalog, tmp_path):
    snapshot_id, _ = _mixed_run(graph_catalog)

    manifest = LexicalRunReporter(graph_catalog.store).write_input_manifest(
        snapshot_id, tmp_path / "run"
    )

    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["snapshot_id"] == snapshot_id
    assert document["input_total"] == 2
    assert [item["source_definition_id"] for item in document["inputs"]] == [1, 2]
    assert all(item["source_definition_sha256"] for item in document["inputs"])


def test_reporter_refuses_a_run_with_an_input_missing_its_disposition(
    graph_catalog, tmp_path
):
    snapshot_id, run_id = _mixed_run(graph_catalog)
    _append_input(
        graph_catalog,
        snapshot_id,
        external_key="report:unprocessed",
        word_id=3,
        definition_id=3,
        examples=[
            {
                "id": 3,
                "source_row_id": 3,
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            }
        ],
    )

    with pytest.raises(ValueError, match="missing dispositions"):
        LexicalRunReporter(graph_catalog.store).write_remediation_report(
            run_id, tmp_path / "run"
        )


def test_quarantine_export_is_internal_sqlite_with_integrity_and_hash(
    graph_catalog, tmp_path
):
    _, run_id = _mixed_run(graph_catalog)

    result = QuarantineExporter(graph_catalog.store).export(
        run_id, tmp_path / "quarantine"
    )

    assert result.database_path.exists()
    assert result.checksum_path.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(result.database_path.read_bytes()).hexdigest()}  "
        f"{result.database_path.name}\n"
    )
    with sqlite3.connect(result.database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT count(*) FROM quarantine_cases"
        ).fetchone() == (1,)
        assert (
            connection.execute("SELECT count(*) FROM evidence_items").fetchone()[0] > 0
        )

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.learning.lexical_remediation import LexicalRemediationService
from src.learning.lexical_reporting import LexicalRunReporter, QuarantineExporter
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.sqlite_reference_importer import (
    SQLiteLexicalReferenceImporter,
    SQLiteReferenceMaterializer,
)


def _write_reference(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE words (
                id INTEGER PRIMARY KEY,
                lemma TEXT NOT NULL,
                pos TEXT NOT NULL,
                ipa_uk TEXT,
                ipa_us TEXT,
                frequency_rank INTEGER,
                cefr_level TEXT,
                source TEXT
            );
            CREATE TABLE definitions (
                id INTEGER PRIMARY KEY,
                word_id INTEGER NOT NULL,
                definition_en TEXT,
                definition_vi TEXT,
                example TEXT,
                source TEXT
            );
            CREATE TABLE sentences (
                id INTEGER PRIMARY KEY,
                text_en TEXT NOT NULL,
                text_vi TEXT,
                difficulty_score REAL,
                cefr_level TEXT,
                audio_path TEXT,
                source TEXT
            );
            CREATE TABLE word_sentences (
                word_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                PRIMARY KEY (word_id, sentence_id)
            );
            """)
        connection.execute("""
            INSERT INTO words VALUES
                (1, 'book', 'noun', '/bʊk/', '/bʊk/', 100, 'A1', 'kaikki')
            """)
        connection.execute("""
            INSERT INTO definitions VALUES
                (1, 1, 'a set of written pages', 'quyển sách', NULL, 'kaikki')
            """)
        connection.execute("""
            INSERT INTO sentences VALUES
                (1, 'Read this book.', 'Hãy đọc quyển sách này.', NULL, 'A1', NULL, 'tatoeba')
            """)
        connection.execute("INSERT INTO word_sentences VALUES (1, 1, 1)")


def test_lexical_53k_contract_preserves_source_and_stops_before_approval(
    graph_catalog, tmp_path: Path
):
    reference_path = tmp_path / "english_dataset.db"
    _write_reference(reference_path)
    source_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    source_mtime_ns = reference_path.stat().st_mtime_ns
    graph_catalog.register_source(
        SourceAssetInput(
            asset_id="contract-reference",
            title="Contract lexical reference",
            locator="https://example.test/contract-reference",
            asset_version="2026-08",
            sha256=source_sha256,
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Contract fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    source_snapshot_id = graph_catalog.record_source_snapshot(
        "contract-reference", reference_path, datetime.now(UTC)
    )

    materialized = SQLiteReferenceMaterializer(
        graph_catalog, tmp_path / "snapshots"
    ).materialize(reference_path, source_snapshot_id)
    imported = SQLiteLexicalReferenceImporter(graph_catalog).import_ranked_definitions(
        materialized.materialized_path,
        materialized.snapshot_id,
        "contract-import",
    )
    remediation = LexicalRemediationService(graph_catalog.store).run(
        materialized.snapshot_id, validation_run_id="contract-remediation"
    )
    output_dir = tmp_path / "run"
    report_path = LexicalRunReporter(graph_catalog.store).write_remediation_report(
        remediation.validation_run_id, output_dir
    )
    quarantine = QuarantineExporter(graph_catalog.store).export(
        remediation.validation_run_id, output_dir
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        LexicalRunReporter(graph_catalog.store)
        .write_input_manifest(materialized.snapshot_id, output_dir)
        .read_text(encoding="utf-8")
    )
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == source_sha256
    assert reference_path.stat().st_mtime_ns == source_mtime_ns
    assert imported.eligible_definitions == 1
    assert manifest["source_definition_count"] == imported.eligible_definitions
    assert manifest["source_linked_example_count"] == imported.source_example_links
    assert manifest["normalized_source_evidence_count"] == 1
    assert manifest["normalized_word_evidence_link_count"] == 1
    assert report["input_total"] == imported.eligible_definitions
    assert report["source_evidence_inventory"] == {
        "normalized_source_evidence_count": 1,
        "normalized_word_evidence_link_count": 1,
    }
    assert report["input_total"] == sum(report["counts_by_state"].values())
    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM content_candidates WHERE state = 'approved'"
        )
        == 0
    )
    assert hashlib.sha256(quarantine.database_path.read_bytes()).hexdigest() == (
        quarantine.checksum_path.read_text(encoding="utf-8").split()[0]
    )
    assert report_path.read_bytes()

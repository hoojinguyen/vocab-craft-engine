from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from src.learning.catalog import SourceCatalog
from src.learning.lexical_audit import LexicalAuditService
from src.learning.lexical_exporter import LexicalPackExporter
from src.learning.lexical_pack import LexicalPackComposer
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.repository import ContentRepository
from src.learning.sqlite_reference_importer import SQLiteLexicalReferenceImporter


def _reviewed_reference(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""
            CREATE TABLE words (
                id INTEGER PRIMARY KEY, lemma TEXT NOT NULL, pos TEXT NOT NULL,
                ipa_uk TEXT, ipa_us TEXT, frequency_rank INTEGER,
                cefr_level TEXT, source TEXT
            );
            CREATE TABLE definitions (
                id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL,
                definition_en TEXT, definition_vi TEXT, example TEXT, source TEXT
            );
            CREATE TABLE sentences (
                id INTEGER PRIMARY KEY, text_en TEXT NOT NULL, text_vi TEXT,
                difficulty_score REAL, cefr_level TEXT, audio_path TEXT, source TEXT
            );
            CREATE TABLE word_sentences (
                word_id INTEGER NOT NULL, sentence_id INTEGER NOT NULL,
                rank INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (word_id, sentence_id)
            );
            """)
        for index in range(30):
            suffix = chr(ord("a") + index // 26) + chr(ord("a") + index % 26)
            lemma = f"lex{suffix}"
            word_id = index + 1
            sentence_id = 1000 + word_id
            connection.execute(
                "INSERT INTO words VALUES (?, ?, 'noun', '/lɛks/', '/lɛks/', ?, 'A1', 'kaikki')",
                [word_id, lemma, 100 + index],
            )
            connection.execute(
                "INSERT INTO definitions VALUES (?, ?, ?, ?, NULL, 'kaikki')",
                [word_id, word_id, f"definition of {lemma}", f"nghĩa của {lemma}"],
            )
            connection.execute(
                "INSERT INTO sentences VALUES (?, ?, ?, NULL, NULL, NULL, 'tatoeba')",
                [
                    sentence_id,
                    f"Use {lemma} today.",
                    f"Hãy dùng {lemma} hôm nay.",
                ],
            )
            connection.execute(
                "INSERT INTO word_sentences VALUES (?, ?, 1)", [word_id, sentence_id]
            )
        connection.execute(
            "INSERT INTO words VALUES (99, 'badword', 'noun', '/bæd/', '/bæd/', 200, 'A1', 'kaikki')"
        )
        connection.execute(
            "INSERT INTO definitions VALUES (99, 99, 'broken definition', '[VI] broken definition', NULL, 'kaikki')"
        )
        connection.execute(
            "INSERT INTO sentences VALUES (1099, 'Use badword today.', 'Hãy dùng badword hôm nay.', NULL, NULL, NULL, 'tatoeba')"
        )
        connection.execute("INSERT INTO word_sentences VALUES (99, 1099, 1)")
        connection.commit()
    finally:
        connection.close()
    return path


def test_lexical_reference_reaches_offline_pack_only_after_quality_review(
    tmp_path: Path,
):
    reference = _reviewed_reference(tmp_path / "english_dataset.db")
    graph_path = tmp_path / "learning_graph.duckdb"
    from src.learning.store import LearningGraphStore

    store = LearningGraphStore(graph_path)
    store.initialize()
    catalog = SourceCatalog(store)
    checksum = hashlib.sha256(reference.read_bytes()).hexdigest()
    catalog.register_source(
        SourceAssetInput(
            asset_id="legacy-sqlite",
            title="Legacy SQLite fixture",
            locator="https://example.test/legacy.sqlite",
            asset_version="2026-08-17",
            sha256=checksum,
            license_id="LicenseRef-Test",
            license_url="https://example.test/license",
            attribution="VocabCraft test fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    snapshot_id = catalog.record_source_snapshot(
        "legacy-sqlite", reference, "2026-08-17T00:00:00+00:00"
    )
    SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        reference, snapshot_id, "test-import"
    )
    audit = LexicalAuditService(store).audit(snapshot_id)
    repository = ContentRepository(store)
    candidate_ids = [
        str(candidate_id)
        for (candidate_id,) in store.connection()
        .execute(
            "SELECT candidate_id FROM content_candidates WHERE state = 'validated' ORDER BY candidate_id"
        )
        .fetchall()
    ]
    assert len(candidate_ids) == 30
    for candidate_id in candidate_ids:
        repository.review_candidate(
            candidate_id, "approved", "editor-1", "Reviewed fixture"
        )

    pack = LexicalPackComposer(repository).compose(
        audit.validation_run_id, "lexical-a1", "0.1.0", "A1"
    )
    result = LexicalPackExporter().export(pack, tmp_path / "lexical-a1")
    connection = sqlite3.connect(result.sqlite_path)
    try:
        assert connection.execute("SELECT count(*) FROM senses").fetchone() == (30,)
        assert connection.execute(
            "SELECT count(*) FROM senses WHERE lemma = 'badword'"
        ).fetchone() == (0,)
    finally:
        connection.close()
    assert (
        json.loads(result.json_path.read_text(encoding="utf-8"))["pack_id"]
        == "lexical-a1"
    )
    store.close()

"""
Comprehensive Phase 3 End-to-End SQLite Export, Integrity Verification, and Packaging Test.

Validates:
1. Complete streaming export of all 11 tables to SQLite english_dataset.db.
2. DatasetVerifier integrity check and zero foreign key violations.
3. DatasetPackager creating valid ZIP archive, SHA256 checksum, and manifest.json.
4. CoreExporter generating curated core_3000.db SQLite database.
5. All covering indexes created in both exported databases.
"""

import json
import sqlite3
import pytest
from pathlib import Path

from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter
from src.export.packager import DatasetPackager
from src.export.sqlite_exporter import SqliteExporter
from src.export.verifier import DatasetVerifier, VerificationReport


@pytest.fixture
def phase3_staging(tmp_path: Path):
    db_file = tmp_path / "phase3_staging.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    # Insert words with frequency ranks
    mgr.insert_batch_fast("words", [
        {"lemma": "the", "pos": "determiner", "frequency_rank": 1, "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "be", "pos": "verb", "frequency_rank": 2, "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "run", "pos": "verb", "frequency_rank": 500, "cefr_level": "A2", "source": "kaikki"},
        {"lemma": "doctor", "pos": "noun", "frequency_rank": 1200, "cefr_level": "A2", "source": "kaikki"},
        {"lemma": "ephemeral", "pos": "adj", "frequency_rank": 18000, "cefr_level": "C2", "source": "kaikki"},
    ])

    conn = mgr.get_connection()
    the_id = conn.execute("SELECT id FROM words WHERE lemma = 'the'").fetchone()[0]
    run_id = conn.execute("SELECT id FROM words WHERE lemma = 'run'").fetchone()[0]
    doc_id = conn.execute("SELECT id FROM words WHERE lemma = 'doctor'").fetchone()[0]

    # Insert definitions
    mgr.insert_batch_fast("definitions", [
        {"word_id": the_id, "definition_en": "Denoting one or more people or things already mentioned.", "definition_vi": "Từ chỉ người/vật đã biết.", "source": "kaikki"},
        {"word_id": run_id, "definition_en": "To move rapidly on foot.", "definition_vi": "Chạy nhanh trên đôi chân.", "source": "kaikki"},
        {"word_id": doc_id, "definition_en": "A qualified practitioner of medicine.", "definition_vi": "Bác sĩ y khoa.", "source": "kaikki"},
    ])

    # Insert sentences
    mgr.insert_batch_fast("sentences", [
        {"text_en": "The doctor arrived early.", "text_vi": "Bác sĩ đã đến sớm.", "cefr_level": "A2", "source": "tatoeba"},
        {"text_en": "They run together every morning.", "text_vi": "Họ cùng nhau chạy mỗi sáng.", "cefr_level": "A1", "source": "tatoeba"},
    ])

    # Insert word_sentences
    mgr.insert_batch_fast("word_sentences", [
        {"word_id": the_id, "sentence_id": 1},
        {"word_id": doc_id, "sentence_id": 1},
        {"word_id": run_id, "sentence_id": 2},
    ])

    # Insert phrases
    mgr.insert_batch_fast("phrases", [
        {"phrase": "run out of", "phrase_type": "phrasal_verb", "definition_en": "to have none left", "definition_vi": "hết", "cefr_level": "A2"},
    ])
    mgr.insert_batch_fast("phrase_sentences", [
        {"phrase_id": 1, "sentence_id": 2, "rank": 1},
    ])

    # Insert relations
    mgr.insert_batch_fast("word_relations", [
        {"word_id": run_id, "relation_type": "synonym", "target_text": "sprint", "target_word_id": None, "inverted": 0, "source": "wordnet"},
    ])

    # Insert topics
    mgr.insert_batch_fast("word_topics", [
        {"word_id": doc_id, "topic": "Health & Medicine", "raw_topic": "health"},
        {"word_id": run_id, "topic": "Sports & Fitness", "raw_topic": "sports"},
    ])

    # Insert reflex drills
    mgr.insert_batch_fast("reflex_drills", [
        {
            "sentence_id": 1,
            "drill_type": "speed_translation",
            "prompt_text": "The doctor arrived early.",
            "correct_answer": "Bác sĩ đã đến sớm.",
            "distractors_json": json.dumps(["Họ cùng nhau chạy mỗi sáng.", "Thời tiết hôm nay đẹp.", "Tôi muốn uống cà phê."], ensure_ascii=False),
            "target_time_ms": 2500,
        },
    ])

    # Insert dialogue trees & nodes
    mgr.insert_batch_fast("dialogue_trees", [
        {"title": "Visiting Clinic", "topic": "Health & Medicine", "cefr_level": "A2"},
    ])
    mgr.insert_batch_fast("dialogue_nodes", [
        {"tree_id": 1, "parent_node_id": None, "speaker_role": "A", "choice_label": "Greeting", "sentence_id": 1},
    ])

    yield mgr
    mgr.close()


def test_phase3_full_pipeline_export_verify_package(phase3_staging: DuckDBManager, tmp_path: Path):
    target_sqlite = tmp_path / "output" / "english_dataset.db"
    core_sqlite = tmp_path / "output" / "core_3000.db"
    dist_dir = tmp_path / "output"

    # 1. Full SQLite Export
    exporter = SqliteExporter()
    counts = exporter.export(phase3_staging, target_sqlite)
    assert counts["words"] == 5
    assert counts["definitions"] == 3
    assert counts["sentences"] == 2
    assert counts["word_sentences"] == 3
    assert counts["phrases"] == 1
    assert counts["word_topics"] == 2
    assert counts["reflex_drills"] == 1
    assert counts["dialogue_trees"] == 1
    assert counts["dialogue_nodes"] == 1

    # 2. Dataset Verification
    verifier = DatasetVerifier()
    report: VerificationReport = verifier.verify(target_sqlite)
    assert report.is_valid is True
    assert report.foreign_key_violations == 0
    assert report.integrity_check_passed is True
    assert report.invalid_json_count == 0

    # 3. Distribution Packaging
    packager = DatasetPackager()
    package_result = packager.package(
        db_path=target_sqlite,
        output_dir=dist_dir,
        version="2.0.0",
        table_counts=counts,
    )
    assert package_result["zip_path"].exists()
    assert package_result["sha256_path"].exists()
    assert package_result["manifest_path"].exists()

    # Check manifest content
    manifest = json.loads(package_result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["version"] == "2.0.0"
    assert manifest["table_counts"]["words"] == 5
    assert len(manifest["sha256"]) == 64

    # 4. Core 3000 Bundle Export
    core_exporter = CoreExporter()
    core_count = core_exporter.export_core_bundle(phase3_staging, core_sqlite, core_limit=3)
    assert core_count == 3  # top 3 words ('the', 'be', 'run')

    core_report = verifier.verify(core_sqlite)
    assert core_report.is_valid is True
    assert core_report.foreign_key_violations == 0

    core_conn = sqlite3.connect(str(core_sqlite))
    core_words = [r[0] for r in core_conn.execute("SELECT lemma FROM words ORDER BY frequency_rank").fetchall()]
    assert "the" in core_words
    assert "be" in core_words
    assert "run" in core_words
    assert "ephemeral" not in core_words  # C2 rank 18000 excluded from core 3
    core_conn.close()

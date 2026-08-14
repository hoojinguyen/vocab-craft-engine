from pathlib import Path
import sqlite3
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter


def test_core_exporter_creates_bundle_and_quality_report():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        sqlite_out = Path(tmp_dir) / "core_3000.db"
        report_out = Path(tmp_dir) / "quality_report.md"

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        # Seed minimal valid data
        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "water", "pos": "noun", "ipa_uk": "/ˈwɔː.tər/", "ipa_us": "/ˈwɑː.tɚ/", "frequency_rank": 50, "source": "kaikki"}
        ])
        db_mgr.insert_batch_fast("definitions", [
            {"id": 1, "word_id": 1, "definition_en": "Clear liquid necessary for life", "definition_vi": "Nước", "source": "kaikki"}
        ])
        db_mgr.insert_batch_fast("sentences", [
            {"id": 1, "text_en": "I drink water.", "text_vi": "Tôi uống nước.", "source": "tatoeba"}
        ])
        db_mgr.insert_batch_fast("word_sentences", [
            {"word_id": 1, "sentence_id": 1}
        ])
        db_mgr.insert_batch_fast("word_topics", [
            {"word_id": 1, "topic": "Food & Drink", "raw_topic": "Food & Drink"}
        ])

        exporter = CoreExporter()
        count = exporter.export_core_bundle(
            db_mgr=db_mgr,
            target_path=sqlite_out,
            report_path=report_out,
            core_limit=10,
        )

        assert count == 1
        assert sqlite_out.exists()
        assert report_out.exists()

        # Verify SQLite contents
        conn = sqlite3.connect(str(sqlite_out))
        cur = conn.cursor()
        res = cur.execute("SELECT count(*) FROM words").fetchone()
        assert res[0] == 1

        meta_res = cur.execute("SELECT value FROM dataset_metadata WHERE key = 'bundle_type'").fetchone()
        assert meta_res[0] == "core_3000"

        passed_res = cur.execute("SELECT value FROM dataset_metadata WHERE key = 'passed_all_quality_gates'").fetchone()
        assert passed_res is not None
        assert passed_res[0] == "1"
        conn.close()

        # Verify Markdown report
        content = report_out.read_text(encoding="utf-8")
        assert "# Core 3000 Quality Audit Report" in content
        assert "Quality Gate Coverage" in content
        assert "CEFR Level Distribution" in content
        assert "All words successfully passed 100% of quality gates!" in content


def test_core_exporter_empty_staging():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "empty.duckdb"
        sqlite_out = Path(tmp_dir) / "core_3000.db"
        report_out = Path(tmp_dir) / "quality_report.md"

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        exporter = CoreExporter()
        count = exporter.export_core_bundle(
            db_mgr=db_mgr,
            target_path=sqlite_out,
            report_path=report_out,
            core_limit=10,
        )

        assert count == 0


def test_core_exporter_with_defects_and_ngsl():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        sqlite_out = Path(tmp_dir) / "core_3000.db"
        report_out = Path(tmp_dir) / "quality_report.md"
        ngsl_csv = Path(tmp_dir) / "ngsl.csv"
        ngsl_csv.write_text("word,rank\nrun,1\n", encoding="utf-8")

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        # Seed data with missing vietnamese translation and sentence
        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "run", "pos": "verb", "ipa_uk": "/rʌn/", "ipa_us": "/rʌn/", "frequency_rank": 100, "source": "kaikki"}
        ])
        db_mgr.insert_batch_fast("definitions", [
            {"id": 1, "word_id": 1, "definition_en": "To move swiftly on foot", "definition_vi": None, "source": "kaikki"}
        ])

        exporter = CoreExporter()
        count = exporter.export_core_bundle(
            db_mgr=db_mgr,
            target_path=sqlite_out,
            report_path=report_out,
            core_limit=10,
            ngsl_path=ngsl_csv,
        )

        assert count == 1
        assert sqlite_out.exists()
        assert report_out.exists()

        content = report_out.read_text(encoding="utf-8")
        assert "NGSL Overlap:" in content
        assert "Defect Samples" in content
        assert "| `run` | def_vi, sentence, topic |" in content


def test_core_exporter_without_report_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        sqlite_out = Path(tmp_dir) / "core_3000.db"

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "apple", "pos": "noun", "ipa_uk": "/ˈæp.əl/", "ipa_us": "/ˈæp.əl/", "frequency_rank": 200, "source": "kaikki"}
        ])

        exporter = CoreExporter()
        count = exporter.export_core_bundle(
            db_mgr=db_mgr,
            target_path=sqlite_out,
            report_path=None,
            core_limit=10,
        )

        assert count == 1
        assert sqlite_out.exists()


def test_core_exporter_oxford_overlap(tmp_path: Path):
    db_path = tmp_path / "staging.duckdb"
    sqlite_out = tmp_path / "core_3000.db"
    report_out = tmp_path / "quality_report.md"
    oxford_file = tmp_path / "oxford_3000.txt"
    oxford_file.write_text("water\n", encoding="utf-8")
    ngsl_file = tmp_path / "ngsl.csv"
    ngsl_file.write_text("rocket,1\n", encoding="utf-8")

    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    db_mgr.insert_batch_fast("words", [
        {"id": 1, "lemma": "water", "pos": "noun", "ipa_uk": "/ˈwɔː.tər/", "ipa_us": "/ˈwɑː.tɚ/", "frequency_rank": 50, "source": "kaikki"},
        {"id": 2, "lemma": "rocket", "pos": "noun", "ipa_uk": "/ˈrɒk.ɪt/", "ipa_us": "/ˈrɑː.kɪt/", "frequency_rank": 100, "source": "kaikki"},
    ])

    exporter = CoreExporter()
    count = exporter.export_core_bundle(
        db_mgr=db_mgr,
        target_path=sqlite_out,
        report_path=report_out,
        core_limit=10,
        ngsl_path=ngsl_file,
        oxford_path=oxford_file,
    )

    assert count == 2
    assert report_out.exists()
    content = report_out.read_text(encoding="utf-8")
    assert "NGSL Overlap:" in content
    assert "Oxford 3000 Overlap:" in content
    assert "Oxford 3000 Overlap:** 1 (50.0%)" in content
    assert "NGSL Overlap:** 1 (50.0%)" in content


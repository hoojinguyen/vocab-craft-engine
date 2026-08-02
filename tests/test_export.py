"""
Unit and Benchmark tests for SQLiteExporter in src.export.sqlite_exporter
"""

import pytest
import sqlite3
from pathlib import Path
from src.db.staging_db import DatabaseManager
from src.export.sqlite_exporter import SQLiteExporter


@pytest.fixture
def populated_db(tmp_path: Path):
    db_file = tmp_path / "export_test.db"
    db_manager = DatabaseManager(db_path=db_file)
    db_manager.init_schema()

    # Populate dummy sample data
    words = [
        {"lemma": "run", "pos": "verb", "ipa_uk": "rʌn", "ipa_us": "rʌn", "frequency_rank": 150, "cefr_level": "A1"},
        {"lemma": "jump", "pos": "verb", "ipa_uk": "dʒʌmp", "ipa_us": "dʒʌmp", "frequency_rank": 400, "cefr_level": "A1"}
    ]
    db_manager.insert_words_batch(words)

    sentences = [
        {"text_en": "I can run fast.", "text_vi": "Tôi có thể chạy nhanh.", "difficulty_score": 1.2, "cefr_level": "A1", "audio_path": "sent_1.mp3", "source": "Tatoeba"},
        {"text_en": "They jump high.", "text_vi": "Họ nhảy cao.", "difficulty_score": 1.5, "cefr_level": "A1", "audio_path": "sent_2.mp3", "source": "Tatoeba"}
    ]
    db_manager.insert_sentences_batch(sentences)

    # Insert sample reflex drill
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
        VALUES (1, 'speed_translation', 'I can run fast.', 'Tôi có thể chạy nhanh.', '["Họ nhảy cao.", "Chào bạn", "Tôi biết"]', 2500);
    """)
    conn.commit()
    db_manager.close()

    return db_file


def test_sqlite_exporter_package_and_verify(populated_db: Path):
    exporter = SQLiteExporter(db_path=populated_db)
    result = exporter.optimize_and_package()

    assert result["path"] == str(populated_db)
    assert result["size_bytes"] > 0
    assert result["size_mb"] >= 0.0

    # Verify zero foreign key violations
    violations = exporter.verify_foreign_keys()
    assert len(violations) == 0


def test_sqlite_exporter_benchmark_speed(populated_db: Path):
    exporter = SQLiteExporter(db_path=populated_db)
    exporter.optimize_and_package()

    avg_ms = exporter.benchmark_reflex_query_speed(iterations=20)
    assert avg_ms >= 0.0
    assert avg_ms < 5.0  # Must be under 5ms benchmark target

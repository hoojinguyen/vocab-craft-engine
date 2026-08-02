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


def test_exporter_creates_phrase_indexes(populated_db: Path):
    db_manager = DatabaseManager(db_path=populated_db)
    db_manager.init_schema()

    db_manager.insert_phrases_batch([
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    phrase_id = db_manager.get_phrase_id_by_text("break a leg")
    db_manager.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": 1, "rank": 1}
    ])

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP INDEX IF EXISTS idx_phrases_cefr;")
    cursor.execute("DROP INDEX IF EXISTS idx_phrases_type;")
    cursor.execute("DROP INDEX IF EXISTS idx_phrase_sentences_phrase;")
    cursor.execute("DROP INDEX IF EXISTS idx_phrase_sentences_sentence;")
    conn.commit()
    db_manager.close()

    exporter = SQLiteExporter(db_path=populated_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(populated_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN ('phrases', 'phrase_sentences');")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_phrases_cefr" in indexes
    assert "idx_phrases_type" in indexes
    assert "idx_phrase_sentences_phrase" in indexes
    assert "idx_phrase_sentences_sentence" in indexes


def test_exporter_phrase_foreign_keys(populated_db: Path):
    db_manager = DatabaseManager(db_path=populated_db)
    db_manager.init_schema()
    db_manager.insert_phrases_batch([
        {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "phrasal verb",
         "cefr_level": "A2", "difficulty_score": 1.8, "definition_en": "Stop trying.",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    phrase_id = db_manager.get_phrase_id_by_text("give up")
    db_manager.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": 1, "rank": 1}
    ])
    db_manager.close()

    exporter = SQLiteExporter(db_path=populated_db)
    violations = exporter.verify_foreign_keys()
    assert len(violations) == 0

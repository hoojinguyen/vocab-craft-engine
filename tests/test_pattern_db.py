import sqlite3
import pytest
from pathlib import Path
from src.db.staging_db import DatabaseManager

@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    return db_mgr

def test_pattern_sentences_schema_and_batch_insert(tmp_db):
    conn = tmp_db.get_connection()
    # Check pattern_sentences table exists and uses WITHOUT ROWID
    tbls = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "pattern_sentences" in tbls

    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pattern_sentences';").fetchone()[0]
    assert "WITHOUT ROWID" in ddl.upper()

    # Insert parent sentence_pattern and sentence to satisfy foreign keys
    tmp_db.insert_sentence_patterns_batch([
        {"pattern_name": "S + V + O", "structure_json": "{}", "example_en": "I love coding", "example_vi": "Tôi thích lập trình", "cefr_level": "A1"}
    ])
    pattern_id = conn.execute("SELECT id FROM sentence_patterns WHERE pattern_name = 'S + V + O'").fetchone()[0]

    tmp_db.insert_sentences_batch([
        {"text_en": "I love coding", "text_vi": "Tôi thích lập trình", "difficulty_score": 1.0, "cefr_level": "A1", "audio_path": None, "source": "test"}
    ])
    sentence_id = conn.execute("SELECT id FROM sentences WHERE text_en = 'I love coding'").fetchone()[0]

    count = tmp_db.insert_pattern_sentences_batch([
        {"pattern_id": pattern_id, "sentence_id": sentence_id, "matched_tokens_json": "[]"}
    ])
    assert count == 1

    # Verify empty mappings returns 0
    assert tmp_db.insert_pattern_sentences_batch([]) == 0

    # Verify duplicate insert is ignored due to PRIMARY KEY (pattern_id, sentence_id)
    dup_count = tmp_db.insert_pattern_sentences_batch([
        {"pattern_id": pattern_id, "sentence_id": sentence_id, "matched_tokens_json": "[]"}
    ])
    assert dup_count == 0

    # Verify data in database
    cursor = conn.execute("SELECT pattern_id, sentence_id, matched_tokens_json FROM pattern_sentences WHERE pattern_id = ? AND sentence_id = ?", (pattern_id, sentence_id))
    row = cursor.fetchone()
    assert row == (pattern_id, sentence_id, "[]")

    tmp_db.close()

import pytest
from src.db.staging_db import DatabaseManager
from main import run_pattern_step

def test_run_pattern_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    # Insert test sentence
    conn = db_mgr.get_connection()
    conn.execute("INSERT INTO sentences (text_en, text_vi, cefr_level) VALUES ('It is easy to learn English.', 'Thật dễ để học tiếng Anh.', 'A2');")
    conn.commit()

    patterns_count, mappings_count = run_pattern_step(db_mgr)
    assert patterns_count >= 1
    assert mappings_count >= 1

    row = conn.execute("SELECT example_en, example_vi FROM sentence_patterns WHERE pattern_name = 'it_is_adj_to_v';").fetchone()
    assert row is not None
    assert row[0] == 'It is easy to learn English.'
    db_mgr.close()


def test_run_pattern_step_empty_db(tmp_path):
    db_path = tmp_path / "test_empty_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    patterns_count, mappings_count = run_pattern_step(db_mgr)
    assert patterns_count == 0
    assert mappings_count == 0
    db_mgr.close()

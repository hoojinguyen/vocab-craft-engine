import pytest
from src.db.staging_db import DatabaseManager
from main import run_quiz_step

def test_run_quiz_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    conn = db_mgr.get_connection()
    conn.execute("INSERT INTO words (id, lemma, pos, cefr_level) VALUES (1, 'abandon', 'verb', 'B2');")
    conn.execute("INSERT INTO sentences (id, text_en, text_vi, cefr_level) VALUES (10, 'She abandoned her car.', 'Cô ấy bỏ xe.', 'B2');")
    conn.commit()

    count = run_quiz_step(db_mgr)
    assert count >= 1

    q_count = conn.execute("SELECT COUNT(*) FROM quiz_questions;").fetchone()[0]
    assert q_count == count
    db_mgr.close()

def test_run_quiz_step_empty_db(tmp_path):
    db_path = tmp_path / "empty_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    count = run_quiz_step(db_mgr)
    assert count == 0

    conn = db_mgr.get_connection()
    q_count = conn.execute("SELECT COUNT(*) FROM quiz_questions;").fetchone()[0]
    assert q_count == 0
    db_mgr.close()

import pytest
from src.db.staging_db import DatabaseManager

@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    return db_mgr

def test_insert_quiz_questions_batch(tmp_db):
    questions = [
        {
            "question_type": "word_mcq",
            "target_type": "word",
            "target_id": 1,
            "prompt_text": "abandon",
            "correct_answer": "rời bỏ",
            "options_json": '["rời bỏ", "đạt được", "thay thế", "bỏ mặc"]',
            "cefr_level": "B2"
        }
    ]
    count = tmp_db.insert_quiz_questions_batch(questions)
    assert count == 1

    conn = tmp_db.get_connection()
    row = conn.execute("SELECT question_type, prompt_text, cefr_level FROM quiz_questions WHERE target_id = 1;").fetchone()
    assert row[0] == "word_mcq"
    assert row[1] == "abandon"
    assert row[2] == "B2"
    tmp_db.close()

def test_insert_quiz_questions_batch_empty(tmp_db):
    count = tmp_db.insert_quiz_questions_batch([])
    assert count == 0
    tmp_db.close()

def test_insert_quiz_questions_batch_multiple(tmp_db):
    questions = [
        {
            "question_type": "word_mcq",
            "target_type": "word",
            "target_id": 10,
            "prompt_text": "apple",
            "correct_answer": "quả táo",
            "options_json": '["quả táo", "quả chuối", "quả cam", "quả nho"]',
            "cefr_level": "A1"
        },
        {
            "question_type": "cloze_fill",
            "target_type": "sentence",
            "target_id": 42,
            "prompt_text": "She ___ an apple.",
            "correct_answer": "ate",
            "options_json": '["ate", "eats", "eating", "eaten"]',
            "cefr_level": "A2"
        }
    ]
    count = tmp_db.insert_quiz_questions_batch(questions)
    assert count == 2

    conn = tmp_db.get_connection()
    rows = conn.execute("SELECT id, question_type, target_type, target_id, prompt_text, correct_answer, options_json, cefr_level FROM quiz_questions ORDER BY id ASC;").fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "word_mcq"
    assert rows[0][7] == "A1"
    assert rows[1][1] == "cloze_fill"
    assert rows[1][7] == "A2"
    tmp_db.close()

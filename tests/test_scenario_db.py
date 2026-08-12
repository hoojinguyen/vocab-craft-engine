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


def test_insert_dialogue_scenarios_batch(tmp_db):
    scenarios = [
        {
            "title": "Ordering Coffee",
            "topic": "Dining",
            "cefr_level": "A2",
            "nodes": [
                {
                    "node_index": 0,
                    "parent_index": None,
                    "speaker_role": "A",
                    "choice_label": None,
                    "text_en": "Hi! What can I get started for you?",
                    "text_vi": "Xin chào! Bạn muốn dùng gì?",
                },
                {
                    "node_index": 1,
                    "parent_index": 0,
                    "speaker_role": "B",
                    "choice_label": "Hot Latte",
                    "text_en": "I'd like a hot latte.",
                    "text_vi": "Cho tôi 1 latte nóng.",
                },
            ],
        }
    ]
    trees_cnt, nodes_cnt = tmp_db.insert_dialogue_scenarios_batch(scenarios)
    assert trees_cnt == 1
    assert nodes_cnt == 2

    conn = tmp_db.get_connection()
    row = conn.execute("SELECT title, root_node_id FROM dialogue_trees WHERE id = 1;").fetchone()
    assert row[0] == "Ordering Coffee"
    assert row[1] is not None

    node_row = conn.execute(
        "SELECT parent_node_id, choice_label FROM dialogue_nodes WHERE tree_id = 1 AND choice_label = 'Hot Latte';"
    ).fetchone()
    assert node_row[0] == row[1]  # Parent is root node
    tmp_db.close()


def test_insert_dialogue_scenarios_batch_empty(tmp_db):
    trees_cnt, nodes_cnt = tmp_db.insert_dialogue_scenarios_batch([])
    assert trees_cnt == 0
    assert nodes_cnt == 0
    tmp_db.close()


def test_insert_dialogue_scenarios_batch_sentence_reuse(tmp_db):
    # Pre-insert a sentence
    conn = tmp_db.get_connection()
    conn.execute(
        "INSERT INTO sentences (text_en, text_vi, cefr_level, source) VALUES (?, ?, ?, ?)",
        ("I'd like a hot latte.", "Cho tôi 1 latte nóng.", "A2", "manual")
    )
    conn.commit()
    existing_sentence_id = conn.execute("SELECT id FROM sentences WHERE text_en = ?;", ("I'd like a hot latte.",)).fetchone()[0]

    scenarios = [
        {
            "title": "Ordering Coffee Duplicate Sentence",
            "topic": "Dining",
            "cefr_level": "A2",
            "nodes": [
                {
                    "node_index": 0,
                    "parent_index": None,
                    "speaker_role": "A",
                    "choice_label": None,
                    "text_en": "What would you like?",
                    "text_vi": "Bạn muốn gì?",
                },
                {
                    "node_index": 1,
                    "parent_index": 0,
                    "speaker_role": "B",
                    "choice_label": "Hot Latte",
                    "text_en": "I'd like a hot latte.",
                    "text_vi": "Cho tôi 1 latte nóng.",
                },
            ],
        }
    ]

    trees_cnt, nodes_cnt = tmp_db.insert_dialogue_scenarios_batch(scenarios)
    assert trees_cnt == 1
    assert nodes_cnt == 2

    node_row = conn.execute(
        "SELECT sentence_id FROM dialogue_nodes WHERE choice_label = 'Hot Latte';"
    ).fetchone()
    assert node_row[0] == existing_sentence_id

    # Verify no duplicate sentence was inserted
    sent_count = conn.execute("SELECT count(*) FROM sentences WHERE text_en = ?;", ("I'd like a hot latte.",)).fetchone()[0]
    assert sent_count == 1
    tmp_db.close()

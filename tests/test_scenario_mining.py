"""Tests for auto dialogue tree mining engine."""

import duckdb
import pytest
from src.nlp.scenario_builder import ScenarioBuilder


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR, text_vi VARCHAR, cefr_level VARCHAR, source VARCHAR)")
    c.execute("""
        INSERT INTO raw_sentences VALUES
        (1, 'Hi! What can I get started for you today?', 'Xin chào! Bạn muốn gọi gì hôm nay?', 'A2', 'OpenSubtitles'),
        (2, 'I would like a hot latte, please.', 'Cho tôi một ly latte nóng.', 'A2', 'OpenSubtitles'),
        (3, 'Just an iced Americano for me, thanks.', 'Cho tôi một ly Americano đá, cảm ơn.', 'A2', 'OpenSubtitles'),
        (4, 'Where is the nearest subway station?', 'Ga tàu điện ngầm gần nhất ở đâu?', 'B1', 'TED-EnVi'),
        (5, 'Go straight for two blocks, it is on your left.', 'Đi thẳng hai dãy nhà, nó ở bên trái.', 'B1', 'TED-EnVi'),
        (6, 'Sorry, I am not from around here.', 'Xin lỗi, tôi không phải người ở đây.', 'B1', 'TED-EnVi')
    """)
    yield c
    c.close()


def test_mine_dialogue_trees_generates_branching_graphs(conn):
    builder = ScenarioBuilder()
    scenarios = builder.mine_dialogue_trees(conn, max_trees_per_topic=2)
    
    assert len(scenarios) >= 1
    first = scenarios[0]
    assert "title" in first
    assert "topic" in first
    assert len(first["nodes"]) == 3
    
    # Node 0 is Speaker A (Partner Prompt)
    assert first["nodes"][0]["speaker_role"] == "A"
    assert first["nodes"][0]["parent_index"] is None
    
    # Node 1 and Node 2 are Speaker B (Learner Choices)
    assert first["nodes"][1]["speaker_role"] == "B"
    assert first["nodes"][1]["parent_index"] == 0
    assert first["nodes"][2]["speaker_role"] == "B"
    assert first["nodes"][2]["parent_index"] == 0

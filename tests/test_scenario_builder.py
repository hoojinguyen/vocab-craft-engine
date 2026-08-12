import pytest
from src.nlp.scenario_builder import ScenarioBuilder

def test_build_all_scenarios_catalog():
    builder = ScenarioBuilder()
    scenarios = builder.build_all_scenarios()
    assert len(scenarios) >= 25

    topics = {s["topic"] for s in scenarios}
    assert "Dining" in topics
    assert "Travel & Directions" in topics
    assert "Hotel & Accommodation" in topics
    assert "Shopping & Retail" in topics
    assert "Work & Business" in topics
    assert "Social & Greetings" in topics
    assert "Healthcare & Medical" in topics
    assert "Daily Conversation" in topics

    for sc in scenarios:
        assert "title" in sc
        assert "topic" in sc
        assert "cefr_level" in sc
        assert len(sc["nodes"]) >= 3
        
        # Verify node indices and parent indices
        indices = {n["node_index"] for n in sc["nodes"]}
        assert 0 in indices  # Root node
        for n in sc["nodes"]:
            assert "speaker_role" in n
            assert "text_en" in n
            assert "text_vi" in n
            if n["parent_index"] is not None:
                assert n["parent_index"] in indices

"""
Unit tests for TopicMapper in src.nlp.topic_mapper
"""

from src.nlp.topic_mapper import TopicMapper


def test_map_known_topics():
    assert TopicMapper.map_topic("computing") == "Technology"
    assert TopicMapper.map_topic("medicine") == "Health & Medicine"
    assert TopicMapper.map_topic("zoology") == "Nature & Animals"
    assert TopicMapper.map_topic("milky way") == "Milky Way"  # covered by fallback


def test_map_topic_is_case_and_whitespace_insensitive():
    assert TopicMapper.map_topic("  Medicine  ") == "Health & Medicine"


def test_map_fallback_normalizes_unmapped_topic():
    assert TopicMapper.map_topic("natural-sciences") == "Natural Sciences"
    assert TopicMapper.map_topic("cooking") == "Food & Drink"

"""
Unit tests for TopicMapper in src.nlp.topic_mapper
"""

from src.nlp.topic_mapper import TopicMapper


def test_map_known_topics():
    assert TopicMapper.map_topic("computing") == "Technology"
    assert TopicMapper.map_topic("medicine") == "Health & Medicine"
    assert TopicMapper.map_topic("zoology") == "Nature & Animals"
    assert TopicMapper.map_topic("milky way") == "General & Everyday"  # covered by fallback


def test_map_topic_is_case_and_whitespace_insensitive():
    assert TopicMapper.map_topic("  Medicine  ") == "Health & Medicine"


def test_map_fallback_normalizes_unmapped_topic():
    from src.nlp.topic_mapper import TopicMapper
    assert TopicMapper.map_topic("some-unknown-domain") == "General & Everyday"


def test_map_topic_keyword_chemistry_collapse():
    from src.nlp.topic_mapper import TopicMapper
    assert TopicMapper.map_topic("Organic Chemistry") == "Science & Mathematics"
    assert TopicMapper.map_topic("Biochemistry") == "Science & Mathematics"
    assert TopicMapper.map_topic("Microbiology") == "Science & Mathematics"
    assert TopicMapper.map_topic("Pathology") == "Health & Medicine"
    assert TopicMapper.map_topic("Mineralogy") == "Science & Mathematics"
    assert TopicMapper.map_topic("Law Enforcement") == "Law & Government"


def test_map_topic_exact_still_wins():
    from src.nlp.topic_mapper import TopicMapper
    assert TopicMapper.map_topic("computing") == "Technology"
    assert TopicMapper.map_topic("MEDICINE") == "Health & Medicine"


def test_map_topic_fallback_is_general():
    from src.nlp.topic_mapper import TopicMapper
    assert TopicMapper.map_topic("rubik's cube") == "General & Everyday"
    assert TopicMapper.map_topic("") == "General & Everyday"


def test_retheme_word_topics_collapses_raw_topics(tmp_path):
    import sqlite3
    from src.nlp.topic_mapper import retheme_word_topics

    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(
        """
        CREATE TABLE word_topics (
            word_id INTEGER, topic TEXT, raw_topic TEXT,
            UNIQUE (word_id, topic)
        );
        """
    )
    conn.executemany(
        "INSERT INTO word_topics (word_id, topic, raw_topic) VALUES (?, ?, ?)",
        [
            (1, "Organic Chemistry", "Organic Chemistry"),
            (1, "Chemistry", "Chemistry"),          # collapses to same theme -> dedup
            (2, "Pathology", "Pathology"),
        ],
    )
    conn.commit()

    retheme_word_topics(conn)

    rows = conn.execute(
        "SELECT word_id, topic, raw_topic FROM word_topics ORDER BY word_id, topic"
    ).fetchall()
    assert rows == [
        (1, "Science & Mathematics", "Organic Chemistry"),
        (2, "Health & Medicine", "Pathology"),
    ]

import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.topic_mapper import TopicMapper
from src.pipeline.steps.transform_relations import TransformRelationsStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_topic_mapper_taxonomy_mapping(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast("words", [
        {"lemma": "doctor", "pos": "noun", "source": "kaikki"},
        {"lemma": "flight", "pos": "noun", "source": "kaikki"},
        {"lemma": "computer", "pos": "noun", "source": "kaikki"},
        {"lemma": "pizza", "pos": "noun", "source": "kaikki"},
        {"lemma": "apple", "pos": "noun", "source": "kaikki"},
        {"lemma": "randomlemmaxyz", "pos": "noun", "source": "kaikki"},
    ])

    mapper = TopicMapper()
    mapped_count = mapper.map_topics(db_mgr)
    assert mapped_count >= 6

    conn = db_mgr.get_connection()
    topics = conn.execute("""
        SELECT w.lemma, wt.topic 
        FROM word_topics wt
        JOIN words w ON wt.word_id = w.id
        ORDER BY w.lemma
    """).fetchall()

    topic_dict = {row[0]: row[1] for row in topics}
    assert topic_dict["doctor"] == "Health & Medicine"
    assert topic_dict["flight"] == "Travel & Transportation"
    assert topic_dict["computer"] == "Technology"
    assert topic_dict["apple"] == "Food & Drink"
    assert topic_dict["randomlemmaxyz"] == "General & Everyday"


def test_topic_mapper_step():
    step = TransformRelationsStep()
    assert "word_topics" in step.produces

import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.topic_mapper import TopicMapper
from src.pipeline.steps.transform_relations import TransformRelationsStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "apple", "pos": "noun", "source": "kaikki"}])
    yield mgr
    mgr.close()


def test_topic_mapper(db_mgr):
    mapper = TopicMapper()
    mapped = mapper.map_topics(db_mgr)
    assert mapped >= 1
    assert db_mgr.count_rows("word_topics") >= 1

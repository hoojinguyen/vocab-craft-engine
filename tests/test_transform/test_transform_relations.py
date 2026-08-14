import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.relation_builder import RelationBuilder
from src.pipeline.steps.transform_relations import TransformRelationsStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_relation_builder_dedup_and_bidirectional(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast("words", [
        {"lemma": "start", "pos": "verb", "source": "kaikki"},
        {"lemma": "begin", "pos": "verb", "source": "kaikki"},
        {"lemma": "create", "pos": "verb", "source": "kaikki"},
    ])

    conn = db_mgr.get_connection()
    start_id = conn.execute("SELECT id FROM words WHERE lemma = 'start'").fetchone()[0]
    begin_id = conn.execute("SELECT id FROM words WHERE lemma = 'begin'").fetchone()[0]

    # Insert relation without target_word_id, and self-referencing relation
    db_mgr.insert_batch_fast("word_relations", [
        {
            "word_id": start_id,
            "relation_type": "synonym",
            "target_text": "begin",
            "target_word_id": None,
            "inverted": 0,
            "source": "wordnet",
        },
        {
            "word_id": start_id,
            "relation_type": "synonym",
            "target_text": "start",
            "target_word_id": start_id,
            "inverted": 0,
            "source": "wordnet",
        },
    ])

    builder = RelationBuilder()
    count = builder.deduplicate_and_link(db_mgr)
    assert count > 0

    # 1. Verify self-referencing relation is deleted
    self_refs = conn.execute("SELECT count(*) FROM word_relations WHERE word_id = target_word_id").fetchone()[0]
    assert self_refs == 0

    # 2. Verify target_word_id was resolved for start -> begin
    rel = conn.execute(
        "SELECT word_id, target_word_id, target_text, inverted FROM word_relations WHERE word_id = ? AND target_text = 'begin'",
        [start_id],
    ).fetchone()
    assert rel is not None
    assert rel[1] == begin_id
    assert rel[3] == 0

    # 3. Verify symmetric inverted relation begin -> start was automatically created
    inv_rel = conn.execute(
        "SELECT word_id, target_word_id, target_text, inverted FROM word_relations WHERE word_id = ? AND target_word_id = ?",
        [begin_id, start_id],
    ).fetchone()
    assert inv_rel is not None
    assert inv_rel[3] == 1


def test_transform_relations_step_attributes():
    step = TransformRelationsStep()
    assert step.name == "transform_relations"
    assert "word_relations" in step.produces
    assert "word_topics" in step.produces

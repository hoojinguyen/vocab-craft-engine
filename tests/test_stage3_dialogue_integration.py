"""Tests for Stage 3 dialogue tree staging integration."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_3_enrich import _build_dialogue_scenarios


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE SEQUENCE dialogue_trees_id_seq START 1;")
    c.execute("CREATE TABLE dialogue_trees (id INTEGER PRIMARY KEY DEFAULT nextval('dialogue_trees_id_seq'), title VARCHAR, topic VARCHAR, cefr_level VARCHAR)")
    c.execute("CREATE TABLE dialogue_nodes (id INTEGER PRIMARY KEY, tree_id INTEGER, parent_node_id INTEGER, choice_label VARCHAR, speaker_role VARCHAR, sentence_id INTEGER)")
    
    c.execute("CREATE SEQUENCE raw_sentences_id_seq START 1;")
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY DEFAULT nextval('raw_sentences_id_seq'), text_en VARCHAR, text_vi VARCHAR, cefr_level VARCHAR, source VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'What coffee do you like?', 'Bạn thích cà phê gì?', 'A2', 'Tatoeba'), (2, 'I like hot latte.', 'Tôi thích latte nóng.', 'A2', 'Tatoeba'), (3, 'I like iced coffee.', 'Tôi thích cà phê đá.', 'A2', 'Tatoeba')")

    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def execute(self, sql, params=()):
            return self.conn.execute(sql, params)
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_build_dialogue_scenarios_populates_staging(conn):
    ctx, db_conn = conn
    _build_dialogue_scenarios(ctx)
    
    assert ctx.duckdb_conn.row_count("dialogue_trees") >= 1
    assert ctx.duckdb_conn.row_count("dialogue_nodes") >= 3

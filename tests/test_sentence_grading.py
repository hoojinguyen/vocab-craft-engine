"""Tests for dynamic sentence difficulty and CEFR grading."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _grade_sentences_dynamically


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_words (id INTEGER PRIMARY KEY, lemma VARCHAR UNIQUE, frequency_rank INTEGER, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_words VALUES (101, 'hello', 100, 'A1'), (102, 'unprecedented', 15000, 'C1')")
    
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'hello world', 2.0, 'B1'), (2, 'unprecedented event', 2.0, 'B1')")
    
    c.execute("CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER)")
    c.execute("INSERT INTO word_sentence_map VALUES (101, 1), (102, 2)")

    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_grade_sentences_dynamically(conn):
    ctx, db_conn = conn
    _grade_sentences_dynamically(ctx, ctx.duckdb_conn)
    
    res = db_conn.execute("SELECT id, difficulty_score, cefr_level FROM raw_sentences ORDER BY id").fetchall()
    # Sentence 1 contains 'hello' (rank 100, A1)
    assert res[0][1] == 100.0
    assert res[0][2] == "A1"
    
    # Sentence 2 contains C1 word 'unprecedented' -> upgraded to C1
    assert res[1][1] == 15000.0
    assert res[1][2] == "C1"

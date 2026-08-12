"""Tests for pure DuckDB SQL CEFR grading."""

from pathlib import Path
import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _apply_cefr_grading


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_words (id INTEGER PRIMARY KEY, lemma VARCHAR, frequency_rank INTEGER, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_words VALUES (1, 'the', NULL, NULL), (2, 'unprecedented', NULL, NULL)")
    
    # Create mock SUBTLEX CSV
    subtlex_csv = tmp_path / "SUBTLEX_US.csv"
    subtlex_csv.write_text("Word,FREQcount,SUBTLWF\nthe,1000000,100.0\nunprecedented,10,0.01\n")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
            
    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_apply_cefr_grading_updates_raw_words_in_sql(conn):
    ctx, db_conn = conn
    _apply_cefr_grading(ctx, ctx.duckdb_conn)
    
    res = db_conn.execute("SELECT lemma, frequency_rank, cefr_level FROM raw_words ORDER BY id").fetchall()
    assert res[0][0] == "the"
    assert res[0][1] == 1  # top rank
    assert res[0][2] == "A1"
    
    assert res[1][0] == "unprecedented"
    assert res[1][1] == 2

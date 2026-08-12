"""Tests for multiprocessing spaCy sentence lemmatization."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _link_word_sentences


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'Cats run fast.'), (2, 'Dogs bark loud.')")
    c.execute("CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER)")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def insert_rows(self, table, rows):
            if not rows: return
            cols = list(rows[0].keys())
            placeholders = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
            self.conn.executemany(sql, [[r[c] for c in cols] for r in rows])
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    ctx.lemma_cache = {"cat": 101, "run": 102, "dog": 103, "bark": 104}
    
    yield ctx, c
    c.close()


def test_link_word_sentences_multiprocessing(conn):
    ctx, db_conn = conn
    _link_word_sentences(ctx, ctx.duckdb_conn)
    
    count = ctx.duckdb_conn.row_count("word_sentence_map")
    assert count >= 3  # verified sentence links populated

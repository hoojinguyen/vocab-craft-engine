"""Tests for DuckDB native CSV corpora ingestion."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_1_ingest import _ingest_corpora_pair


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE SEQUENCE raw_sentences_id_seq START 1;")
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY DEFAULT nextval('raw_sentences_id_seq'), text_en VARCHAR, text_vi VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR, source VARCHAR)")
    
    # Create sample EN and VI files
    en_file = tmp_path / "test_en.txt"
    vi_file = tmp_path / "test_vi.txt"
    en_file.write_text("Hello world.\nHow are you?\n")
    vi_file.write_text("Chào thế giới.\nBạn khỏe không?\n")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, en_file, vi_file
    c.close()


def test_ingest_corpora_pair_loads_sentences(conn):
    ctx, en_file, vi_file = conn
    _ingest_corpora_pair(ctx.duckdb_conn, en_file, vi_file, "TestCorpus")
    assert ctx.duckdb_conn.row_count("raw_sentences") == 2

"""Tests for Stage 4 DuckDB Native SQLite Export."""

from pathlib import Path
import duckdb
import sqlite3
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_4_export import stage_4_export


@pytest.fixture
def mock_context(tmp_path):
    duckdb_path = tmp_path / "staging.duckdb"
    sqlite_path = tmp_path / "output.db"
    conn = duckdb.connect(str(duckdb_path))
    
    # Setup staging tables with sample data
    conn.execute("CREATE TABLE raw_words (id INTEGER PRIMARY KEY, lemma VARCHAR UNIQUE, pos VARCHAR, ipa_uk VARCHAR, ipa_us VARCHAR, frequency_rank INTEGER, cefr_level VARCHAR)")
    conn.execute("INSERT INTO raw_words VALUES (1, 'hello', 'intj', '/həˈloʊ/', '/həˈloʊ/', 100, 'A1')")
    
    conn.execute("CREATE TABLE raw_definitions (id INTEGER PRIMARY KEY, lemma VARCHAR, definition_en VARCHAR, definition_vi VARCHAR, example VARCHAR, source VARCHAR)")
    conn.execute("INSERT INTO raw_definitions VALUES (10, 'hello', 'a greeting', 'lời chào', 'Hello world', 'Kaikki')")
    
    conn.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR UNIQUE, text_vi VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR, source VARCHAR)")
    conn.execute("INSERT INTO raw_sentences VALUES (100, 'Hello world', 'Chào thế giới', 1.0, 'A1', 'Tatoeba')")
    
    conn.execute("CREATE TABLE raw_phrases (id INTEGER PRIMARY KEY, phrase VARCHAR UNIQUE, phrase_type VARCHAR, pos VARCHAR, cefr_level VARCHAR, difficulty_score DOUBLE, definition_en VARCHAR, definition_vi VARCHAR, ipa VARCHAR)")
    conn.execute("CREATE TABLE collocations (id INTEGER PRIMARY KEY, phrase VARCHAR, meaning_vi VARCHAR, pos_pattern VARCHAR, cefr_level VARCHAR)")
    conn.execute("CREATE TABLE raw_relations (id INTEGER PRIMARY KEY, lemma VARCHAR, relation_type VARCHAR, target_text VARCHAR, target_word_id INTEGER, inverted INTEGER DEFAULT 0, source VARCHAR)")
    conn.execute("CREATE TABLE word_topics (word_id INTEGER, topic VARCHAR, raw_topic VARCHAR)")
    conn.execute("CREATE TABLE reflex_drills (id INTEGER PRIMARY KEY, sentence_id INTEGER, drill_type VARCHAR, prompt_text VARCHAR, correct_answer VARCHAR, distractors_json VARCHAR, target_time_ms INTEGER)")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)

    ctx = PipelineContext(
        raw_dir=tmp_path,
        processed_dir=tmp_path,
        output_dir=tmp_path,
    )
    ctx.duckdb_conn = MockDuckDB(conn)
    ctx.sqlite_path = sqlite_path
    ctx.lemma_cache = {"hello": 1}
    
    yield ctx
    conn.close()


def test_stage4_export_creates_sqlite_db_and_copies_data(mock_context):
    stage_4_export(mock_context)
    assert mock_context.sqlite_path.exists()
    
    # Verify contents in exported SQLite
    sqlite_conn = sqlite3.connect(mock_context.sqlite_path)
    res = sqlite_conn.execute("SELECT lemma, cefr_level FROM words").fetchall()
    assert res == [("hello", "A1")]
    sqlite_conn.close()

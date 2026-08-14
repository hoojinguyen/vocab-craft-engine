import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.pipeline.steps.ingest_wordnet import IngestWordNetStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_wordnet_ingestor_basic(db_mgr: DuckDBManager):
    ingestor = WordNetIngestor()
    inserted = ingestor.ingest(db_mgr, limit=50)
    assert inserted > 0
    assert db_mgr.count_rows("words") > 0
    assert db_mgr.count_rows("word_relations") > 0


def test_wordnet_ingestion_valid_word_ids_and_definitions(db_mgr: DuckDBManager):
    ingestor = WordNetIngestor()
    count = ingestor.ingest(db_mgr, limit=100)
    assert count > 0

    conn = db_mgr.get_connection()
    # Check that word_id in word_relations has multiple distinct valid word IDs (not hardcoded to 1)
    relations = conn.execute("SELECT id, word_id, relation_type, target_text FROM word_relations").fetchall()
    assert len(relations) > 0
    word_ids = {r[1] for r in relations}
    assert len(word_ids) > 1

    # Check that WordNet definitions are inserted
    defs_count = conn.execute("SELECT count(*) FROM definitions WHERE source = 'wordnet'").fetchone()[0]
    assert defs_count > 0

    # Check relation types coverage
    relation_types = {r[2] for r in relations}
    assert "synonym" in relation_types or "antonym" in relation_types or "hypernym" in relation_types

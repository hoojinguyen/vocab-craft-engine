import pytest
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.pipeline.steps.ingest_wordnet import IngestWordNetStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_wordnet_ingestor(db_mgr):
    ingestor = WordNetIngestor()
    inserted = ingestor.ingest(db_mgr, limit=50)
    assert inserted > 0
    assert db_mgr.count_rows("words") > 0
    assert db_mgr.count_rows("word_relations") > 0

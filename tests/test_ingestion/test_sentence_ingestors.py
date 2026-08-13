import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.pipeline.steps.ingest_tatoeba import IngestTatoebaStep
from src.pipeline.steps.ingest_opus import IngestOpusStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_tatoeba_ingestor(db_mgr, tmp_path):
    sent_file = tmp_path / "sentences.csv"
    sent_file.write_text("1\teng\tHello world\n2\tvie\tXin chào thế giới\n")
    links_file = tmp_path / "links.csv"
    links_file.write_text("1\t2\n")

    ingestor = TatoebaIngestor()
    inserted = ingestor.ingest_files(db_mgr, sent_file, links_file)
    assert inserted == 1
    assert db_mgr.count_rows("sentences") == 1


def test_opus_ingestor(db_mgr, tmp_path):
    en_file = tmp_path / "data.en"
    en_file.write_text("This is a simple sentence.\nAnother valid sentence here.\n")
    vi_file = tmp_path / "data.vi"
    vi_file.write_text("Đây là một câu đơn giản.\nMột câu khác ở đây.\n")

    ingestor = OpusIngestor()
    inserted = ingestor.ingest_pair(db_mgr, en_file, vi_file, source="opus")
    assert inserted == 2
    assert db_mgr.count_rows("sentences") == 2

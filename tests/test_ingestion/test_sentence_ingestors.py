import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.pipeline.steps.ingest_tatoeba import IngestTatoebaStep
from src.pipeline.steps.ingest_opus import IngestOpusStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_tatoeba_bidirectional_and_filtering(db_mgr: DuckDBManager, tmp_path: Path):
    sent_file = tmp_path / "sentences.csv"
    # 1: eng valid, 2: vie valid
    # 3: vie valid, 4: eng valid
    # 5: fra (should be ignored), 6: deu (should be ignored)
    # 7: eng too short ("Hi"), 8: vie ("Chào")
    lines = [
        "1\teng\tThis is a valid sentence.\n",
        "2\tvie\tĐây là một câu hợp lệ.\n",
        "3\tvie\tTạm biệt và hẹn gặp lại.\n",
        "4\teng\tGoodbye and see you soon.\n",
        "5\tfra\tBonjour le monde.\n",
        "6\tdeu\tHallo Welt.\n",
        "7\teng\tHi.\n",
        "8\tvie\tChào.\n",
    ]
    sent_file.write_text("".join(lines), encoding="utf-8")

    links_file = tmp_path / "links.csv"
    links_lines = [
        "1\t2\n",  # eng -> vie
        "3\t4\n",  # vie -> eng (reverse link)
        "5\t6\n",  # fra -> deu
        "7\t8\n",  # too short
    ]
    links_file.write_text("".join(links_lines), encoding="utf-8")

    ingestor = TatoebaIngestor()
    inserted = ingestor.ingest_files(db_mgr, sent_file, links_file)
    assert inserted == 2

    conn = db_mgr.get_connection()
    rows = conn.execute("SELECT text_en, text_vi FROM sentences ORDER BY text_en").fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "Goodbye and see you soon."
    assert rows[0][1] == "Tạm biệt và hẹn gặp lại."
    assert rows[1][0] == "This is a valid sentence."
    assert rows[1][1] == "Đây là một câu hợp lệ."


def test_opus_ingestor_length_filtering(db_mgr: DuckDBManager, tmp_path: Path):
    en_file = tmp_path / "data.en"
    en_file.write_text("This is a simple sentence.\nToo short\nAnother valid sentence here.\n", encoding="utf-8")
    vi_file = tmp_path / "data.vi"
    vi_file.write_text("Đây là một câu đơn giản.\nNgắn\nMột câu khác ở đây.\n", encoding="utf-8")

    ingestor = OpusIngestor()
    inserted = ingestor.ingest_pair(db_mgr, en_file, vi_file, source="opus")
    assert inserted == 2
    assert db_mgr.count_rows("sentences") == 2

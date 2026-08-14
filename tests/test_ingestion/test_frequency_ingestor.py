import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.frequency_ingestor import FrequencyIngestor


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_frequency_ranking_population(db_mgr: DuckDBManager, tmp_path: Path):
    # Pre-populate sample words in words table
    db_mgr.insert_batch_fast("words", [
        {"lemma": "the", "pos": "determiner", "source": "kaikki"},
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "guitar", "pos": "noun", "source": "kaikki"},
        {"lemma": "ephemeral", "pos": "adj", "source": "kaikki"},
        {"lemma": "unknownwordxyz", "pos": "noun", "source": "kaikki"},
    ])

    subtlex_csv = tmp_path / "SUBTLEX_US.csv"
    csv_content = (
        "Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW,rank\n"
        "the,20000000,100.0,7.0,1000000,7.0,1\n"
        "run,50000,10.0,4.7,5000,4.7,600\n"
        "guitar,5000,2.0,3.7,500,3.7,2500\n"
        "ephemeral,50,0.1,1.7,5,1.7,18000\n"
    )
    subtlex_csv.write_text(csv_content, encoding="utf-8")

    ingestor = FrequencyIngestor()
    updated = ingestor.populate_frequency_ranks(db_mgr, subtlex_csv)
    assert updated >= 4

    conn = db_mgr.get_connection()
    row_the = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'the'").fetchone()
    assert row_the[0] == 1
    assert row_the[1] == "A1"

    row_run = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'run'").fetchone()
    assert row_run[0] == 600
    assert row_run[1] == "A2"

    row_guitar = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'guitar'").fetchone()
    assert row_guitar[0] == 2500
    assert row_guitar[1] == "B1"

    row_eph = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'ephemeral'").fetchone()
    assert row_eph[0] == 18000
    assert row_eph[1] == "C2"

    # Default fallback for unranked word
    row_unk = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'unknownwordxyz'").fetchone()
    assert row_unk[0] is None
    assert row_unk[1] == "C2"

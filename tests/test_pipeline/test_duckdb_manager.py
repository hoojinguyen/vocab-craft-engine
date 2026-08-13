import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test_staging.duckdb"
    manager = DuckDBManager(db_path=db_path)
    manager.init_schema()
    yield manager
    manager.close()


def test_init_schema_creates_tables(db_manager):
    conn = db_manager.get_connection()
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    assert "words" in tables
    assert "_pipeline_meta" in tables


def test_insert_batch_words(db_manager):
    rows = [
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "walk", "pos": "verb", "source": "kaikki"},
    ]
    inserted = db_manager.insert_batch("words", rows)
    assert inserted == 2
    assert db_manager.count_rows("words") == 2


def test_insert_batch_dedup(db_manager):
    rows = [{"lemma": "run", "pos": "verb", "source": "kaikki"}]
    db_manager.insert_batch("words", rows)
    db_manager.insert_batch("words", rows)  # duplicate
    assert db_manager.count_rows("words") == 1


def test_count_rows_empty(db_manager):
    assert db_manager.count_rows("words") == 0


def test_save_and_get_step_meta(db_manager):
    db_manager.save_step_meta(
        step_name="ingest_kaikki",
        status="success",
        source_hash="abc123",
        row_count=50000,
        duration_secs=120.5,
        error_message=None,
    )
    meta = db_manager.get_step_meta("ingest_kaikki")
    assert meta is not None
    assert meta["status"] == "success"
    assert meta["source_hash"] == "abc123"
    assert meta["row_count"] == 50000


def test_get_step_meta_missing(db_manager):
    assert db_manager.get_step_meta("nonexistent") is None


def test_save_and_get_checkpoint(db_manager):
    db_manager.save_checkpoint("ingest_kaikki", "line_50000", 50000, '{"offset": 123456}')
    cp = db_manager.get_last_checkpoint("ingest_kaikki")
    assert cp is not None
    assert cp["batch_id"] == "line_50000"
    assert cp["rows_written"] == 50000


def test_clear_checkpoints(db_manager):
    db_manager.save_checkpoint("ingest_kaikki", "line_50000", 50000, None)
    db_manager.clear_checkpoints("ingest_kaikki")
    assert db_manager.get_last_checkpoint("ingest_kaikki") is None


def test_translation_cache_roundtrip(db_manager):
    db_manager.save_translation("hello", "xin chào", "argos")
    result = db_manager.get_translation("hello")
    assert result == "xin chào"


def test_translation_cache_miss(db_manager):
    assert db_manager.get_translation("unknown") is None


def test_translations_batch(db_manager):
    db_manager.save_translation("hello", "xin chào", "argos")
    db_manager.save_translation("goodbye", "tạm biệt", "argos")
    results = db_manager.get_translations_batch(["hello", "goodbye", "missing"])
    assert results["hello"] == "xin chào"
    assert results["goodbye"] == "tạm biệt"
    assert "missing" not in results

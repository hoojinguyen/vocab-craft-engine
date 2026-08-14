import json
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.pipeline.steps.ingest_kaikki import IngestKaikkiStep
from src.pipeline.core.context import PipelineContext


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_kaikki_ingestor_parses_json_lines(db_mgr, tmp_path):
    sample_file = tmp_path / "kaikki_sample.json"
    entry1 = {
        "word": "run",
        "pos": "verb",
        "lang": "English",
        "sounds": [{"ipa": "/rʌn/"}],
        "senses": [{"glosses": ["to move fast"], "examples": [{"text": "I run fast"}]}],
    }
    entry2 = {
        "word": "walk",
        "pos": "verb",
        "lang": "English",
        "sounds": [{"ipa": "/wɔːk/"}],
        "senses": [{"glosses": ["to move on foot"]}],
    }
    sample_file.write_text(json.dumps(entry1) + "\n" + json.dumps(entry2) + "\n")

    ingestor = KaikkiIngestor()
    inserted = ingestor.ingest(db_mgr, sample_file)

    assert inserted >= 2
    assert db_mgr.count_rows("words") == 2
    assert db_mgr.count_rows("definitions") == 2


def test_kaikki_ingestor_foreign_key_batch_order(db_mgr, tmp_path, monkeypatch):
    import src.ingestion.kaikki_ingestor as ka_module
    monkeypatch.setattr(ka_module, "KAIKKI_BATCH_SIZE", 5)

    sample_file = tmp_path / "kaikki_many_senses.json"
    entry = {
        "word": "test",
        "pos": "noun",
        "lang": "English",
        "senses": [{"glosses": [f"sense {i}"]} for i in range(20)],
    }
    sample_file.write_text(json.dumps(entry) + "\n")

    ingestor = KaikkiIngestor()
    inserted = ingestor.ingest(db_mgr, sample_file)
    assert inserted == 1
    assert db_mgr.count_rows("words") == 1
    assert db_mgr.count_rows("definitions") == 20


def test_ingest_kaikki_step_attributes():
    step = IngestKaikkiStep()
    assert step.name == "ingest_kaikki"
    assert step.depends_on == ["schema_init"]
    assert set(step.produces) == {"words", "definitions"}


def test_kaikki_ingestor_handles_duplicate_lemma_pos(db_mgr, tmp_path):
    sample_file = tmp_path / "kaikki_dup.json"
    entry1 = {
        "word": "cat",
        "pos": "noun",
        "lang": "English",
        "senses": [{"glosses": ["feline 1"]}],
    }
    entry2 = {
        "word": "dog",
        "pos": "noun",
        "lang": "English",
        "senses": [{"glosses": ["canine 1"]}],
    }
    entry3 = {
        "word": "cat",
        "pos": "noun",
        "lang": "English",
        "senses": [{"glosses": ["feline 2"]}],
    }
    sample_file.write_text(json.dumps(entry1) + "\n" + json.dumps(entry2) + "\n" + json.dumps(entry3) + "\n")

    ingestor = KaikkiIngestor()
    inserted = ingestor.ingest(db_mgr, sample_file)

    assert inserted == 2
    assert db_mgr.count_rows("words") == 2
    assert db_mgr.count_rows("definitions") == 3


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


def test_ingest_kaikki_step_attributes():
    step = IngestKaikkiStep()
    assert step.name == "ingest_kaikki"
    assert step.depends_on == ["schema_init"]
    assert set(step.produces) == {"words", "definitions"}

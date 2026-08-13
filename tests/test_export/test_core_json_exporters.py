import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter
from src.export.json_exporter import JsonExporter
from src.pipeline.steps.export_core3000 import ExportCore3000Step
from src.pipeline.steps.export_json import ExportJsonStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    yield mgr, tmp_path
    mgr.close()


def test_json_exporter(db_mgr):
    staging_mgr, tmp_path = db_mgr
    json_path = tmp_path / "dataset.json"

    exporter = JsonExporter()
    count = exporter.export(staging_mgr, json_path)

    assert count >= 1
    assert json_path.exists()

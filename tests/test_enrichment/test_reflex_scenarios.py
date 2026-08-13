import pytest
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder
from src.pipeline.steps.enrich_reflex import EnrichReflexStep
from src.pipeline.steps.enrich_scenarios import EnrichScenariosStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("sentences", [{"text_en": "The dog run fast.", "text_vi": "Con chó chạy nhanh."}])
    yield mgr
    mgr.close()


def test_reflex_builder(db_mgr):
    builder = ReflexBuilder()
    count = builder.build(db_mgr)
    assert count >= 1
    assert db_mgr.count_rows("reflex_drills") >= 1


def test_scenario_builder(db_mgr):
    builder = ScenarioBuilder()
    count = builder.build(db_mgr)
    assert count >= 1
    assert db_mgr.count_rows("dialogue_trees") >= 1

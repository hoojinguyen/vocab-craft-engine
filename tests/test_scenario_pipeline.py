import pytest
from src.db.staging_db import DatabaseManager
from main import run_scenario_step

def test_run_scenario_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    trees_count, nodes_count = run_scenario_step(db_mgr)
    assert trees_count >= 25
    assert nodes_count >= 75

    conn = db_mgr.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM dialogue_trees;").fetchone()[0]
    assert count >= 25
    db_mgr.close()

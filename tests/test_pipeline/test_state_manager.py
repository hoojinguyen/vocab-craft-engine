import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.dag import DAG
from src.pipeline.core.state_manager import StateManager


class DummyStep(BaseStep):
    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        pass


class StepA(DummyStep):
    name = "step_a"
    depends_on = []
    produces = ["words"]


class StepB(DummyStep):
    name = "step_b"
    depends_on = ["step_a"]
    produces = ["definitions"]


@pytest.fixture
def db_manager(tmp_path):
    manager = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    manager.init_schema()
    yield manager
    manager.close()


@pytest.fixture
def dag():
    return DAG([StepA(), StepB()])


def test_should_skip_no_previous_run(db_manager, dag):
    state_mgr = StateManager(db_manager)
    step_a = StepA()
    skip, reason = state_mgr.should_skip(step_a, dag)
    assert skip is False
    assert "No previous" in reason or "not completed" in reason.lower() or "missing" in reason.lower() or "no" in reason.lower()


def test_should_skip_cached(db_manager, dag):
    state_mgr = StateManager(db_manager)
    step_a = StepA()
    h = step_a.compute_source_hash()
    state_mgr.record_success(step_a.name, source_hash=h, row_count=10, duration_secs=1.0)

    skip, reason = state_mgr.should_skip(step_a, dag)
    assert skip is True
    assert "Cached" in reason or "cached" in reason.lower() or "hash" in reason.lower()


def test_should_skip_hash_changed(db_manager, dag, tmp_path):
    state_mgr = StateManager(db_manager)
    src_file = tmp_path / "input.txt"
    src_file.write_text("v1")

    step_a = StepA()
    step_a.source_files = [src_file]
    h1 = step_a.compute_source_hash()
    state_mgr.record_success(step_a.name, source_hash=h1, row_count=10, duration_secs=1.0)

    # Modify source file
    src_file.write_text("v2 content update")
    skip, reason = state_mgr.should_skip(step_a, dag)
    assert skip is False
    assert "hash" in reason.lower() or "changed" in reason.lower()


def test_should_skip_forced_step(db_manager, dag):
    state_mgr = StateManager(db_manager)
    step_a = StepA()
    h = step_a.compute_source_hash()
    state_mgr.record_success(step_a.name, source_hash=h, row_count=10, duration_secs=1.0)

    skip, reason = state_mgr.should_skip(step_a, dag, force_steps={"step_a"})
    assert skip is False
    assert "force" in reason.lower()


def test_should_skip_cascade_downstream_invalidation(db_manager, dag):
    state_mgr = StateManager(db_manager)
    step_a = StepA()
    step_b = StepB()

    state_mgr.record_success(step_a.name, source_hash=step_a.compute_source_hash(), row_count=10, duration_secs=1.0)
    state_mgr.record_success(step_b.name, source_hash=step_b.compute_source_hash(), row_count=5, duration_secs=0.5)

    # Force step_a to re-run
    state_mgr.invalidate_step("step_a", dag)

    # step_b should now be invalidated because upstream step_a was invalidated
    skip, reason = state_mgr.should_skip(step_b, dag)
    assert skip is False

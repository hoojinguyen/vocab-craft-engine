import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.result import StepResult, StepStatus


class StepA(BaseStep):
    name = "step_a"
    description = "Step A"
    depends_on = []
    produces = ["words"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class StepB(BaseStep):
    name = "step_b"
    description = "Step B"
    depends_on = ["step_a"]
    produces = ["definitions"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


class FailingStep(BaseStep):
    name = "failing_step"
    description = "Failing step"
    depends_on = ["step_a"]
    produces = ["error_table"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        raise RuntimeError("Step failed explicitly")


@pytest.fixture
def ctx(tmp_path):
    class DummyArgs:
        max_retries = 0
        tui = False

    db_mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    db_mgr.init_schema()
    context = PipelineContext(db_manager=db_mgr, args=DummyArgs())
    yield context
    db_mgr.close()


def test_orchestrator_runs_dag_success(ctx):
    orchestrator = PipelineOrchestrator(steps=[StepA(), StepB()])
    summary = orchestrator.run(ctx)

    assert summary.has_failures is False
    assert len(summary.results) == 2
    assert summary.results[0].step_name == "step_a"
    assert summary.results[1].step_name == "step_b"
    assert summary.results[0].status == StepStatus.SUCCESS
    assert summary.results[1].status == StepStatus.SUCCESS


def test_orchestrator_handles_failure_and_stops(ctx):
    orchestrator = PipelineOrchestrator(steps=[StepA(), FailingStep(), StepB()])
    summary = orchestrator.run(ctx)

    assert summary.has_failures is True
    # StepA succeeds, FailingStep fails, StepB is skipped/not run because it depends on step_a / failure in pipeline
    failed_results = [r for r in summary.results if r.status == StepStatus.FAILED]
    assert len(failed_results) == 1
    assert failed_results[0].step_name == "failing_step"


def test_orchestrator_dry_run(ctx):
    class DummyArgs:
        dry_run = True
        tui = False

    ctx.args = DummyArgs()
    orchestrator = PipelineOrchestrator(steps=[StepA(), StepB()])
    summary = orchestrator.run(ctx)

    assert summary.has_failures is False
    for res in summary.results:
        assert res.status == StepStatus.SKIPPED
        assert "[DRY-RUN]" in res.message

import time
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.dag import DAG
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.result import StepResult, StepStatus


class SleepStepA(BaseStep):
    name = "sleep_a"
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        time.sleep(0.3)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=10)


class SleepStepB(BaseStep):
    name = "sleep_b"
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        time.sleep(0.3)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=20)


class OptionalStepC(BaseStep):
    name = "opt_c"
    optional = True

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=5)


def test_orchestrator_runs_level_steps_concurrently(tmp_path: Path):
    db_file = tmp_path / "test_conc.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    step_a = SleepStepA()
    step_b = SleepStepB()

    orchestrator = PipelineOrchestrator(steps=[step_a, step_b], max_workers=2)
    ctx = PipelineContext(db_manager=mgr)

    t0 = time.perf_counter()
    summary = orchestrator.run(ctx)
    elapsed = time.perf_counter() - t0

    assert summary.has_failures is False
    assert len(summary.results) == 2
    # Two 0.3s steps running in parallel must take < 0.55s total
    assert elapsed < 0.55, f"Expected parallel execution < 0.55s, but took {elapsed:.2f}s"
    mgr.close()


def test_orchestrator_skips_disabled_optional_step(tmp_path: Path):
    db_file = tmp_path / "test_opt.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    step_c = OptionalStepC()
    orchestrator = PipelineOrchestrator(steps=[step_c])
    ctx = PipelineContext(db_manager=mgr, enabled_optional_steps=[])

    summary = orchestrator.run(ctx)
    assert summary.has_failures is False
    assert len(summary.results) == 1
    assert summary.results[0].status == StepStatus.SKIPPED
    assert "not enabled" in summary.results[0].message
    mgr.close()

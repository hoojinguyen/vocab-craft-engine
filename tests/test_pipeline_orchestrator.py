import pytest
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.result import StepResult
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.orchestrator import PipelineOrchestrator


class StepA(BaseStep):
    name = "step_a"
    description = "Step A"
    def should_skip(self, context):
        return False, ""
    def run(self, context):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


class StepB(BaseStep):
    name = "step_b"
    description = "Step B"
    def should_skip(self, context):
        return True, "Checkpoint exists"
    def run(self, context):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class FailingStep(BaseStep):
    name = "failing_step"
    description = "Failing Step"
    def should_skip(self, context):
        return False, ""
    def run(self, context):
        raise RuntimeError("Step failed")


def test_registry_filter():
    reg = StepRegistry()
    a, b = StepA(), StepB()
    reg.register(a)
    reg.register(b)

    assert len(reg.get_all_steps()) == 2
    assert reg.get_step("step_a") == a

    inc = reg.filter_steps(include_steps=["step_a"])
    assert len(inc) == 1 and inc[0] == a

    skp = reg.filter_steps(skip_steps=["step_a"])
    assert len(skp) == 1 and skp[0] == b


def test_orchestrator_execution(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())
    reg.register(StepB())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert len(summary.results) == 2
    assert summary.results[0].status == StepStatus.SUCCESS
    assert summary.results[1].status == StepStatus.SKIPPED


def test_orchestrator_dry_run(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = True

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert summary.results[0].status == StepStatus.SKIPPED
    assert "Dry-run mode" in summary.results[0].message


def test_orchestrator_failing_step(tmp_path):
    reg = StepRegistry()
    reg.register(FailingStep())
    reg.register(StepA())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert summary.has_failures
    assert len(summary.results) == 1
    assert summary.results[0].status == StepStatus.FAILED
    assert "Step failed" in summary.results[0].message


def test_orchestrator_step_filtering(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())
    reg.register(StepB())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = "step_a, step_b"
    mock_args.skip_steps = "step_b"
    mock_args.dry_run = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert len(summary.results) == 1
    assert summary.results[0].step_name == "step_a"


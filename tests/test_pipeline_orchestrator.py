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


def test_registry_duplicate_step_raises_error():
    reg = StepRegistry()
    reg.register(StepA())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(StepA())


def test_registry_unknown_include_step_raises_error():
    reg = StepRegistry()
    reg.register(StepA())
    with pytest.raises(ValueError, match="Unknown step name"):
        reg.filter_steps(include_steps=["non_existent_step"])


class ShouldSkipFailingStep(BaseStep):
    name = "should_skip_failing_step"
    description = "Failing in should_skip"

    def should_skip(self, context):
        raise RuntimeError("should_skip exploded")

    def run(self, context):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS)


def test_orchestrator_should_skip_exception(tmp_path):
    reg = StepRegistry()
    reg.register(ShouldSkipFailingStep())

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
    assert "should_skip exploded" in summary.results[0].message


def test_orchestrator_skips_save_step_status_on_dry_run_and_skip(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())
    reg.register(StepB())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    orchestrator.state_manager.save_step_status = MagicMock()

    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = True

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert summary.results[0].status == StepStatus.SKIPPED
    orchestrator.state_manager.save_step_status.assert_not_called()

    mock_args.dry_run = False
    summary2 = orchestrator.run(ctx)
    # StepB is skipped by should_skip
    assert summary2.results[1].status == StepStatus.SKIPPED
    # save_step_status should only have been called for StepA (SUCCESS), not StepB (SKIPPED)
    assert orchestrator.state_manager.save_step_status.call_count == 1
    orchestrator.state_manager.save_step_status.assert_called_once_with("step_a", "SUCCESS", summary2.results[0].execution_time_seconds, 5)


def test_orchestrator_handles_save_step_status_failure_gracefully(tmp_path, caplog):
    reg = StepRegistry()
    reg.register(StepA())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    orchestrator.state_manager.save_step_status = MagicMock(side_effect=RuntimeError("IO Error writing state"))

    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert summary.results[0].status == StepStatus.SUCCESS
    assert "Failed to save step status" in caplog.text


def test_registry_unknown_skip_step_raises_error():
    reg = StepRegistry()
    reg.register(StepA())
    with pytest.raises(ValueError, match="Unknown step name"):
        reg.filter_steps(skip_steps=["non_existent_step"])


def test_orchestrator_clears_state_on_non_dry_run(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    orchestrator.state_manager.clear_state = MagicMock()

    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None

    # When dry_run is True, clear_state is NOT called
    mock_args.dry_run = True
    ctx_dry = PipelineContext(db_manager=MagicMock(), args=mock_args)
    orchestrator.run(ctx_dry)
    orchestrator.state_manager.clear_state.assert_not_called()

    # When dry_run is False, clear_state IS called
    mock_args.dry_run = False
    ctx_run = PipelineContext(db_manager=MagicMock(), args=mock_args)
    orchestrator.run(ctx_run)
    orchestrator.state_manager.clear_state.assert_called_once()




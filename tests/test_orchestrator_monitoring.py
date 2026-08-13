import json
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import StepResult, StepStatus
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext


class StepA(BaseStep):
    name = "step_a"
    description = "Step A"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class StepB(BaseStep):
    name = "step_b"
    description = "Step B"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=20)


class FlakyStep(BaseStep):
    name = "flaky_step"
    description = "Flaky step that fails twice then succeeds"

    def __init__(self, fail_count=2):
        self.fail_count = fail_count
        self.attempts = 0

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError(f"Transient error attempt {self.attempts}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=15)


def test_orchestrator_resume_skips_completed_steps(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    log_dir = tmp_path / "logs"
    registry = StepRegistry()
    registry.register(StepA())
    registry.register(StepB())

    orchestrator = PipelineOrchestrator(registry=registry, state_file=state_file)
    orchestrator.state_manager.save_step_status("step_a", "SUCCESS", 1.0, 10)

    mock_args = MagicMock()
    mock_args.tui = False
    mock_args.dry_run = False
    mock_args.resume = True
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.max_retries = 2
    mock_args.tui = False
    mock_args.log_dir = str(log_dir)

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert len(summary.results) == 2
    assert summary.results[0].step_name == "step_a"
    assert summary.results[0].status == StepStatus.SKIPPED
    assert "Skipped via --resume (already completed in previous run)" in summary.results[0].message
    assert summary.results[1].step_name == "step_b"
    assert summary.results[1].status == StepStatus.SUCCESS


def test_orchestrator_auto_retry_integration(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    log_dir = tmp_path / "logs"
    registry = StepRegistry()
    flaky = FlakyStep(fail_count=2)
    registry.register(flaky)

    orchestrator = PipelineOrchestrator(registry=registry, state_file=state_file)

    mock_args = MagicMock()
    mock_args.tui = False
    mock_args.dry_run = False
    mock_args.resume = False
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.max_retries = 3
    mock_args.tui = False
    mock_args.log_dir = str(log_dir)

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert summary.results[0].status == StepStatus.SUCCESS
    assert summary.results[0].retry_count == 2
    assert flaky.attempts == 3


def test_orchestrator_run_logger_report_generation(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    log_dir = tmp_path / "logs"
    registry = StepRegistry()
    registry.register(StepA())

    orchestrator = PipelineOrchestrator(registry=registry, state_file=state_file)

    mock_args = MagicMock()
    mock_args.tui = False
    mock_args.dry_run = False
    mock_args.resume = False
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.max_retries = 3
    mock_args.tui = False
    mock_args.log_dir = str(log_dir)

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    latest_run_file = log_dir / "latest_run.json"
    assert latest_run_file.exists()

    with open(latest_run_file, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    assert report_data["status"] == "SUCCESS"
    assert report_data["summary_metrics"]["total_steps"] == 1
    assert report_data["steps"][0]["step_name"] == "step_a"

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus, StepResult, PipelineSummary
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.state_manager import StateManager


class DummyStep(BaseStep):
    name = "dummy_step"
    description = "A dummy step for testing core foundation"

    def should_skip(self, context: PipelineContext):
        return False, "Not skipping"

    def run(self, context: PipelineContext) -> StepResult:
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


def test_pipeline_context_init():
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    assert ctx.db_manager == mock_db
    assert ctx.args == mock_args
    assert ctx.shared_data == {}


def test_step_result_and_summary():
    res = StepResult(step_name="test", status=StepStatus.SUCCESS, execution_time_seconds=1.5, items_processed=5)
    assert res.status == StepStatus.SUCCESS
    assert res.items_processed == 5

    summary = PipelineSummary(total_time_seconds=1.5, results=[res], has_failures=False)
    assert not summary.has_failures
    assert len(summary.results) == 1


def test_dummy_step_execution():
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = DummyStep()
    skip, reason = step.should_skip(ctx)
    assert not skip
    assert reason == "Not skipping"

    result = step.run(ctx)
    assert result.status == StepStatus.SUCCESS
    assert result.items_processed == 10


def test_state_manager(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    sm = StateManager(state_file=state_file)

    initial = sm.load_state()
    assert initial == {}

    sm.save_step_status("step1", "SUCCESS", 2.5, 100)
    saved = sm.load_state()
    assert saved["step1"]["status"] == "SUCCESS"
    assert saved["step1"]["duration"] == 2.5
    assert saved["step1"]["items"] == 100

    sm.clear_state()
    cleared = sm.load_state()
    assert cleared == {}


import pytest
from src.pipeline.core.result import StepStatus, StepResult


def test_step_status_retrying():
    assert StepStatus.RETRYING.value == "RETRYING"


def test_step_result_new_fields_defaults():
    res = StepResult(step_name="test_step", status=StepStatus.SUCCESS)
    assert res.retry_count == 0
    assert res.error_traceback is None
    assert res.data_metrics == {}


def test_step_result_new_fields_custom():
    res = StepResult(
        step_name="test_step",
        status=StepStatus.RETRYING,
        retry_count=2,
        error_traceback="Traceback (most recent call last): ...",
        data_metrics={"rows_passed": 100, "rows_failed": 2},
    )
    assert res.retry_count == 2
    assert res.error_traceback == "Traceback (most recent call last): ..."
    assert res.data_metrics == {"rows_passed": 100, "rows_failed": 2}

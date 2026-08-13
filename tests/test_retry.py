import pytest
from unittest.mock import MagicMock
from src.pipeline.core.retry import RetryPolicy
from src.pipeline.core.result import StepResult, StepStatus


class DummyStep:
    name = "dummy_step"
    description = "Dummy description"

    def __init__(self, fail_times=0):
        self.attempts = 0
        self.fail_times = fail_times

    def run(self, context):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError(f"Failure attempt {self.attempts}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=50)


def test_retry_policy_success_first_try():
    step = DummyStep(fail_times=0)
    policy = RetryPolicy(max_retries=3, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock())
    assert res.status == StepStatus.SUCCESS
    assert res.retry_count == 0
    assert step.attempts == 1


def test_retry_policy_recovers_after_retry():
    step = DummyStep(fail_times=2)
    callback_calls = []

    def on_retry(attempt, max_retries, exc):
        callback_calls.append((attempt, max_retries, str(exc)))

    policy = RetryPolicy(max_retries=3, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock(), on_retry_callback=on_retry)
    assert res.status == StepStatus.SUCCESS
    assert res.retry_count == 2
    assert step.attempts == 3
    assert len(callback_calls) == 2
    assert callback_calls[0] == (1, 3, "Failure attempt 1")
    assert callback_calls[1] == (2, 3, "Failure attempt 2")


def test_retry_policy_exhaustion():
    step = DummyStep(fail_times=5)
    callback_calls = []

    def on_retry(attempt, max_retries, exc):
        callback_calls.append((attempt, max_retries, str(exc)))

    policy = RetryPolicy(max_retries=2, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock(), on_retry_callback=on_retry)
    assert res.status == StepStatus.FAILED
    assert res.retry_count == 2
    assert step.attempts == 3
    assert "Failure attempt 3" in res.message
    assert res.error is not None
    assert res.error_traceback is not None
    assert "RuntimeError: Failure attempt 3" in res.error_traceback
    assert len(callback_calls) == 2

import time
import logging
import traceback
from typing import Optional, Callable, Any
from src.pipeline.core.result import StepResult, StepStatus
from src.pipeline.core.context import PipelineContext

logger = logging.getLogger(__name__)


class RetryPolicy:
    """Encapsulates execution of a pipeline step with configurable retry backoff logic."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def execute_with_retry(
        self,
        step: Any,
        context: PipelineContext,
        on_retry_callback: Optional[Callable[[int, int, Exception], None]] = None
    ) -> StepResult:
        """Executes a step with exponential backoff retries upon failure.

        Args:
            step: The step object with a `run(context)` method and `name` attribute.
            context: The PipelineContext passed to `step.run()`.
            on_retry_callback: Optional callback invoked on retry attempts with parameters
                               (attempt_number, max_retries, exception).

        Returns:
            StepResult: The outcome of the step execution.
        """
        attempt = 0

        while attempt <= self.max_retries:
            step_start = time.monotonic()
            try:
                if attempt > 0:
                    logger.warning(
                        "[%s] Retrying step (Attempt %d/%d)...",
                        step.name, attempt, self.max_retries
                    )

                res = step.run(context)
                res.retry_count = attempt
                if res.execution_time_seconds == 0.0:
                    res.execution_time_seconds = round(time.monotonic() - step_start, 2)
                return res

            except Exception as e:
                duration = round(time.monotonic() - step_start, 2)
                tb_str = traceback.format_exc()

                if attempt < self.max_retries:
                    if on_retry_callback:
                        on_retry_callback(attempt + 1, self.max_retries, e)
                    sleep_time = self.backoff_factor * (2 ** attempt)
                    logger.warning(
                        "[%s] Attempt %d failed after %.2fs: %s. Sleeping %.1fs...",
                        step.name, attempt + 1, duration, e, sleep_time
                    )
                    time.sleep(sleep_time)
                    attempt += 1
                else:
                    logger.error(
                        "[%s] Step failed after %d retries (%.2fs): %s",
                        step.name, self.max_retries, duration, e
                    )
                    return StepResult(
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        execution_time_seconds=duration,
                        retry_count=attempt,
                        message=str(e),
                        error=e,
                        error_traceback=tb_str
                    )

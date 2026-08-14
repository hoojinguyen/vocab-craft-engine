"""Thread-safe Progress Reporter Protocol for Pipeline Steps."""

import time
from typing import Callable, Optional


class ProgressReporter:
    """Dispatches progress updates with throttling to avoid UI event spam."""

    def __init__(
        self,
        callback: Optional[Callable[[str, int, int, str], None]] = None,
        throttle_interval: float = 0.08,
    ):
        self.callback = callback
        self.throttle_interval = throttle_interval
        self._last_emitted: dict[str, float] = {}

    def emit_progress(self, step_name: str, current: int, total: int, message: str = "") -> None:
        if not self.callback:
            return

        now = time.monotonic()
        last_time = self._last_emitted.get(step_name, 0.0)

        # Always emit on 0, completion, or when throttle interval has elapsed
        if current >= total or current == 0 or (now - last_time) >= self.throttle_interval:
            self._last_emitted[step_name] = now
            self.callback(step_name, current, total, message)


class StepProgress:
    """Tracks progress for an individual pipeline step."""

    def __init__(self, step_name: str, total: int, reporter: Optional[ProgressReporter] = None):
        self.step_name = step_name
        self.total = max(1, total)
        self.current = 0
        self.reporter = reporter

    def advance(self, count: int = 1, message: str = "") -> None:
        self.current = min(self.total, self.current + count)
        if self.reporter:
            self.reporter.emit_progress(self.step_name, self.current, self.total, message)

    def track_batch(self, count: int, message: str = ""):
        """Context manager to auto-advance progress when a batch completes."""
        step = self

        class BatchContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    step.advance(count, message)

        return BatchContext()

"""
Pipeline Progress Terminal User Interface (TUI) Application using Textual.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding

from src.monitoring.tui.widgets import (
    HeaderWidget,
    StepListWidget,
    MetricsCard,
    LogStreamWidget,
)

logger = logging.getLogger(__name__)


class TUILoggingHandler(logging.Handler):
    """Custom logging handler redirecting records to the PipelineProgressApp log stream."""

    def __init__(self, app: "PipelineProgressApp"):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            time_str = time.strftime("%H:%M:%S", time.localtime(record.created))
            level = record.levelname
            step_idx = getattr(self.app, "current_step_idx", "?")

            if msg.startswith("=== START:"):
                step_name = msg.replace("=== START:", "").strip()
                formatted = f"[bold cyan]▶ STEP {step_idx}: {step_name.upper()}[/bold cyan]"
            elif msg.startswith("=== END:"):
                formatted = ""
            else:
                formatted = f"   [dim]{time_str}[/dim] [{level}] {msg}"

            if formatted:
                self.app.add_log(formatted)
        except Exception:
            self.handleError(record)


class PipelineProgressApp(App):
    """Interactive Terminal User Interface for Monitoring Pipeline Execution."""

    TITLE = "VOCAB CRAFT ENGINE - PIPELINE MONITOR"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("p", "toggle_pause", "Pause/Resume", show=True),
        Binding("r", "refresh_view", "Refresh", show=True),
    ]

    def __init__(
        self,
        enabled: bool = True,
        title: str = "VOCAB CRAFT ENGINE - PIPELINE MONITOR",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.enabled = enabled
        self.title_str = title
        self.title = self.title_str
        self.header_widget = HeaderWidget(title=self.title_str)
        self.step_list = StepListWidget()
        self.metrics_card = MetricsCard()
        self.log_stream = LogStreamWidget()
        self.original_handlers: List[logging.Handler] = []
        self.dashboard_handler: Optional[TUILoggingHandler] = None
        self._worker_func: Optional[Callable[[], None]] = None
        self.start_time = time.time()
        self.logs_buffer: List[str] = []
        self.current_step_idx: str | int = "?"
        self.is_paused = False

    @property
    def steps_data(self) -> Dict[str, Dict[str, Any]]:
        """Return the dictionary of steps data for inspection/compatibility."""
        return self.step_list.steps_data

    def compose(self) -> ComposeResult:
        yield self.header_widget
        yield self.step_list
        yield self.metrics_card
        yield self.log_stream

    def set_steps(self, step_names: List[str]) -> None:
        self.step_list.init_steps(step_names)

    def set_worker(self, worker_func: Callable[[], None]) -> None:
        self._worker_func = worker_func

    def add_log(self, message: str) -> None:
        self.logs_buffer.append(message)
        if len(self.logs_buffer) > 10:
            self.logs_buffer.pop(0)
        try:
            if self.is_running:
                self.call_from_thread(self._append_log_to_ui, message)
        except Exception:
            pass

    def _append_log_to_ui(self, message: str) -> None:
        try:
            self.log_stream.write_log(message)
        except Exception:
            pass

    def update_step_status(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics: str = "",
        metrics_str: str = "",
    ) -> None:
        m = metrics or metrics_str
        self.step_list.update_step(step_name, status, duration, items, retries, m)
        try:
            if self.is_running:
                self.call_from_thread(
                    self.step_list.update_step,
                    step_name,
                    status,
                    duration,
                    items,
                    retries,
                    m,
                )
        except Exception:
            pass

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics: str = "",
        metrics_str: str = "",
    ) -> None:
        """Alias for update_step_status for backward compatibility."""
        self.update_step_status(
            step_name=step_name,
            status=status,
            duration=duration,
            items=items,
            retries=retries,
            metrics=metrics,
            metrics_str=metrics_str,
        )

    def on_mount(self) -> None:
        self._setup_logging_redirection()
        self.set_interval(1.0, self._periodic_refresh)

        if self._worker_func:
            self.run_worker_in_background()

    def _setup_logging_redirection(self) -> None:
        """Temporarily suspend stdout/stderr StreamHandlers and route logs to dashboard."""
        root_logger = logging.getLogger()
        self.dashboard_handler = TUILoggingHandler(self)
        self.dashboard_handler.setLevel(logging.INFO)
        self.original_handlers = []

        for handler in list(root_logger.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                self.original_handlers.append(handler)

        root_logger.addHandler(self.dashboard_handler)

    def _restore_logging(self) -> None:
        """Gracefully restore original logging handlers."""
        root_logger = logging.getLogger()
        if self.dashboard_handler and self.dashboard_handler in root_logger.handlers:
            root_logger.removeHandler(self.dashboard_handler)
        if self.original_handlers:
            for handler in self.original_handlers:
                root_logger.addHandler(handler)
            self.original_handlers = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._restore_logging()

    def _periodic_refresh(self) -> None:
        elapsed = time.time() - self.start_time
        self.header_widget.update_status(
            status="PAUSED" if self.is_paused else "RUNNING",
            elapsed=elapsed,
            workers=4,
        )

    @work(thread=True)
    def run_worker_in_background(self) -> None:
        if self._worker_func:
            try:
                self._worker_func()
            except Exception as e:
                logger.error("Pipeline worker execution failed: %s", e)
            finally:
                self.call_from_thread(self._restore_logging)
                self.call_from_thread(self._on_worker_finished)

    def _on_worker_finished(self) -> None:
        self.header_widget.update_status("COMPLETED", time.time() - self.start_time)

    def action_toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        logger.info("Pipeline %s", "PAUSED" if self.is_paused else "RESUMED")

    def action_refresh_view(self) -> None:
        self.refresh()

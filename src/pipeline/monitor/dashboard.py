import logging
import time
from collections.abc import Callable
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, RichLog


class DashboardLoggingHandler(logging.Handler):
    """Custom logging handler to redirect log records to the TextualPipelineDashboard."""

    def __init__(self, dashboard: "TextualPipelineDashboard"):
        super().__init__()
        self.dashboard = dashboard
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.dashboard.add_log(msg)
        except Exception:
            self.handleError(record)


class TextualPipelineDashboard(App):
    """Real-time Terminal UI dashboard for monitoring pipeline execution using Textual."""

    TITLE = "VOCAB CRAFT ENGINE - PIPELINE MONITOR"
    CSS = """
    DataTable {
        height: auto;
        min-height: 8;
        max-height: 50%;
    }
    RichLog {
        height: 1fr;
    }
    """

    def __init__(self, enabled: bool = True, title: str = "VOCAB CRAFT ENGINE - PIPELINE MONITOR"):
        super().__init__()
        self.enabled = enabled
        self.title_str = title
        self.steps_data: dict[str, dict[str, Any]] = {}
        self.original_handlers: list[logging.Handler] = []
        self.dashboard_handler: DashboardLoggingHandler | None = None
        self._worker_func: Callable[[], None] | None = None
        self.start_time = time.time()
        self.logs_buffer: list[str] = []
        # Ensure title reflects the parameter
        self.title = self.title_str

    def set_steps(self, step_names: list[str]) -> None:
        """Initialize the map of pipeline steps to track."""
        for name in step_names:
            self.steps_data[name] = {
                "status": "PENDING",
                "duration": 0.0,
                "items": 0,
                "retries": 0,
                "metrics": ""
            }

    def set_worker(self, worker_func: Callable[[], None]) -> None:
        """Set the pipeline execution function to run in the background."""
        self._worker_func = worker_func

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True)
        yield DataTable(id="steps_table")
        yield RichLog(id="logs", highlight=True, markup=True)

    def on_mount(self) -> None:
        """Called when app starts."""
        table = self.query_one(DataTable)
        self.col_keys = table.add_columns("#", "Step Name", "Status", "Time (s)", "Items", "Retries", "Metrics")
        
        # Populate initial rows
        for idx, (name, data) in enumerate(self.steps_data.items(), 1):
            table.add_row(
                str(idx),
                name,
                "PENDING ⏸",
                "0.00s",
                "0",
                "0",
                "",
                key=name
            )
            
        self._setup_logging_redirection()
        
        if self._worker_func:
            self.run_pipeline_worker()

    @work(thread=True)
    def run_pipeline_worker(self) -> None:
        """Execute the pipeline in a background thread."""
        try:
            if self._worker_func:
                self._worker_func()
        finally:
            self.call_from_thread(self._restore_logging)
            self.call_from_thread(self.add_log, "[bold green]Pipeline execution completed. Press Ctrl+C to exit.[/bold green]")

    def _setup_logging_redirection(self) -> None:
        """Temporarily suspend stdout/stderr StreamHandlers and route logs to dashboard."""
        self.original_handlers = []
        self.dashboard_handler = DashboardLoggingHandler(self)
        root_logger = logging.getLogger()

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

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics_str: str = ""
    ) -> None:
        """Update step progress, execution state, and metrics. Safe to call from threads."""
        if step_name not in self.steps_data:
            self.steps_data[step_name] = {}

        self.steps_data[step_name].update({
            "status": status,
            "duration": duration,
            "items": items,
            "retries": retries,
            "metrics": metrics_str
        })
        
        def do_update():
            st = status
            if st == "SUCCESS":
                status_cell = "[bold green]SUCCESS[/bold green]"
            elif st == "FAILED":
                status_cell = "[bold red]FAILED ✖[/bold red]"
            elif st == "RUNNING":
                status_cell = "[bold cyan]RUNNING ⏳[/bold cyan]"
            elif "RETRY" in st:
                status_cell = f"[bold yellow]{st}[/bold yellow]"
            elif st == "SKIPPED":
                status_cell = "[dim white]SKIPPED ⏭[/dim white]"
            else:
                status_cell = "[dim]PENDING ⏸[/dim]"
                
            try:
                table = self.query_one(DataTable)
                table.update_cell(step_name, self.col_keys[2], status_cell, update_width=True)
                table.update_cell(step_name, self.col_keys[3], f"{duration:.2f}s", update_width=True)
                table.update_cell(step_name, self.col_keys[4], f"{items:,}", update_width=True)
                table.update_cell(step_name, self.col_keys[5], str(retries), update_width=True)
                table.update_cell(step_name, self.col_keys[6], str(metrics_str), update_width=True)
            except Exception:
                pass
                
        try:
            self.call_from_thread(do_update)
        except Exception:
            pass

    def add_log(self, log_line: str) -> None:
        """Append a log line to the live log stream buffer. Safe to call from threads."""
        self.logs_buffer.append(log_line)
        if len(self.logs_buffer) > 10:
            self.logs_buffer.pop(0)

        def do_log():
            try:
                logs = self.query_one(RichLog)
                logs.write(log_line)
            except Exception:
                pass
                
        try:
            self.call_from_thread(do_log)
        except Exception:
            pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._restore_logging()

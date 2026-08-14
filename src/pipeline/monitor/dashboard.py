"""
Live DAG Pipeline Dashboard Application using Textual.
"""

from collections.abc import Callable
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import psutil
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable

from src.pipeline.monitor.widgets import (
    DAGPanel,
    HeaderWidget,
    LogStreamWidget,
    StepDetailWidget,
    StepTable,
    TelemetryPanel,
)

logger = logging.getLogger(__name__)


class DashboardLoggingHandler(logging.Handler):
    """Routes logging records to the dashboard log stream."""

    def __init__(self, app: "TextualPipelineDashboard"):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            time_str = time.strftime("%H:%M:%S", time.localtime(record.created))
            level = record.levelname

            if msg.startswith("=== START:"):
                step_name = msg.replace("=== START:", "").strip()
                formatted = f"[bold cyan]▶ START STEP:[/bold cyan] [bold white]{step_name}[/bold white]"
            elif msg.startswith("=== END:"):
                step_name = msg.replace("=== END:", "").strip()
                formatted = f"[bold green]✔ FINISHED STEP:[/bold green] [bold white]{step_name}[/bold white]"
            elif level in ("ERROR", "CRITICAL"):
                formatted = f"   [dim]{time_str}[/dim] [bold red][{level}][/bold red] {msg}"
            elif level == "WARNING":
                formatted = f"   [dim]{time_str}[/dim] [bold yellow][{level}][/bold yellow] {msg}"
            else:
                formatted = f"   [dim]{time_str}[/dim] [{level}] {msg}"

            self.app.add_log(formatted)
        except Exception:
            self.handleError(record)


class TextualPipelineDashboard(App):
    """Terminal User Interface for Live DAG Pipeline Monitoring."""

    TITLE = "VOCAB CRAFT ENGINE — PIPELINE MONITOR V2"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("p", "toggle_pause", "Pause/Resume", show=True),
        Binding("r", "refresh_view", "Refresh", show=True),
    ]

    CSS = """
    Screen {
        layout: vertical;
        background: #1e1e2e;
    }
    #main_container {
        layout: horizontal;
        height: 1fr;
    }
    #right_pane {
        layout: vertical;
        width: 1fr;
        height: 100%;
    }
    """

    def __init__(self, enabled: bool = True, title: str = TITLE, **kwargs):
        super().__init__(**kwargs)
        self.enabled = enabled
        self.title_str = title
        self.title = self.title_str
        self.header_widget = HeaderWidget(title=title)
        self.dag_panel = DAGPanel()
        self.step_table = StepTable()
        self.step_detail = StepDetailWidget()
        self.log_stream = LogStreamWidget()
        self.telemetry_panel = TelemetryPanel()

        self.step_metadata: Dict[str, Dict[str, Any]] = {}
        self.selected_step_name: Optional[str] = None
        self._worker_func: Optional[Callable[[], None]] = None
        self.original_handlers: List[logging.Handler] = []
        self.logging_handler: Optional[DashboardLoggingHandler] = None
        self.dashboard_handler: Optional[DashboardLoggingHandler] = None
        self.start_time = time.time()
        self.is_paused = False
        self.logs_buffer: List[str] = []

    @property
    def steps_data(self) -> Dict[str, Dict[str, Any]]:
        return self.step_metadata

    def compose(self) -> ComposeResult:
        yield self.header_widget
        with Horizontal(id="main_container"):
            yield self.dag_panel
            with Vertical(id="right_pane"):
                yield self.step_table
                yield self.step_detail
                yield self.log_stream
        yield self.telemetry_panel

    def set_dag_levels(self, execution_levels: List[List[str]], step_info_map: Optional[Dict[str, Any]] = None) -> None:
        self.dag_panel.init_dag(execution_levels)
        all_steps = [s for lvl in execution_levels for s in lvl]
        self.step_table.init_steps(all_steps)

        for step_name in all_steps:
            info = (step_info_map or {}).get(step_name, {})
            deps = info.get("depends_on", [])
            prods = info.get("produces", [])
            self.step_metadata[step_name] = {
                "name": step_name,
                "status": "PENDING",
                "description": info.get("description", ""),
                "type": info.get("type", "cpu"),
                "depends_on": ", ".join(deps) if isinstance(deps, list) else str(deps or "None"),
                "produces": ", ".join(prods) if isinstance(prods, list) else str(prods or "None"),
                "items": 0,
                "duration": 0.0,
                "retries": 0,
                "error": "",
                "metrics": "",
            }
        if all_steps and not self.selected_step_name:
            self.selected_step_name = all_steps[0]

    def set_steps(self, step_names: List[str]) -> None:
        """Compatibility helper."""
        self.set_dag_levels([[s] for s in step_names])

    def set_worker(self, worker_func: Callable[[], None]) -> None:
        self._worker_func = worker_func

    def _safe_call(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Execute callback directly if on app thread, or via call_from_thread if on worker thread."""
        if not self.is_running:
            return
        try:
            import threading
            if self._thread_id == threading.get_ident():
                callback(*args, **kwargs)
            else:
                self.call_from_thread(callback, *args, **kwargs)
        except Exception:
            pass

    def add_log(self, message: str) -> None:
        self.logs_buffer.append(message)
        if len(self.logs_buffer) > 10:
            self.logs_buffer.pop(0)
        if self.is_running:
            self._safe_call(self.log_stream.write_log, message)

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        error_or_metrics: str = "",
        metrics: str = "",
        metrics_str: str = "",
        **kwargs: Any,
    ) -> None:
        err = error_or_metrics if "FAIL" in status else ""
        met = metrics or metrics_str or (error_or_metrics if "FAIL" not in status else "")
        if step_name in self.step_metadata:
            self.step_metadata[step_name].update({
                "status": status,
                "duration": duration,
                "items": items,
                "retries": retries,
                "error": err,
                "metrics": met,
            })
        else:
            self.step_metadata[step_name] = {
                "name": step_name,
                "status": status,
                "description": "",
                "type": "cpu",
                "depends_on": "None",
                "produces": "None",
                "items": items,
                "duration": duration,
                "retries": retries,
                "error": err,
                "metrics": met,
            }

        if self.is_running:
            self._safe_call(self.dag_panel.update_node_status, step_name, status)
            self._safe_call(
                self.step_table.update_step_status, step_name, status, duration, items, retries
            )
            if self.selected_step_name == step_name:
                self._safe_call(
                    self.step_detail.display_step, self.step_metadata[step_name]
                )

    def update_step_status(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics: str = "",
        metrics_str: str = "",
        **kwargs: Any,
    ) -> None:
        self.update_step(
            step_name=step_name,
            status=status,
            duration=duration,
            items=items,
            retries=retries,
            error_or_metrics=metrics,
            metrics_str=metrics_str,
            **kwargs,
        )

    def update_step_progress(self, step_name: str, current: int, total: int, message: str = "") -> None:
        if step_name in self.step_metadata:
            self.step_metadata[step_name]["items"] = current
        if self.is_running:
            self._safe_call(
                self.step_table.update_step_progress, step_name, current, total, message
            )

    def on_mount(self) -> None:
        self._setup_logging_redirection()
        self.set_interval(1.0, self._periodic_telemetry_refresh)
        if self.selected_step_name and self.selected_step_name in self.step_metadata:
            self.step_detail.display_step(self.step_metadata[self.selected_step_name])

        if self._worker_func:
            self.run_worker_in_background()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row_key = event.row_key.value if hasattr(event.row_key, "value") else str(event.row_key)
        if row_key in self.step_metadata:
            self.selected_step_name = row_key
            self.step_detail.display_step(self.step_metadata[row_key])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value if hasattr(event.row_key, "value") else str(event.row_key)
        if row_key in self.step_metadata:
            self.selected_step_name = row_key
            self.step_detail.display_step(self.step_metadata[row_key])

    def _setup_logging_redirection(self) -> None:
        root_logger = logging.getLogger()
        self.logging_handler = DashboardLoggingHandler(self)
        self.logging_handler.setLevel(logging.INFO)
        self.dashboard_handler = self.logging_handler
        self.original_handlers = []
        for handler in list(root_logger.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                self.original_handlers.append(handler)
        root_logger.addHandler(self.logging_handler)

    def _restore_logging(self) -> None:
        root_logger = logging.getLogger()
        if self.logging_handler and self.logging_handler in root_logger.handlers:
            root_logger.removeHandler(self.logging_handler)
        for handler in self.original_handlers:
            root_logger.addHandler(handler)
        self.original_handlers = []

    def _periodic_telemetry_refresh(self) -> None:
        elapsed = time.time() - self.start_time
        self.header_widget.update_status(
            status="PAUSED" if self.is_paused else "RUNNING",
            elapsed=elapsed,
            workers=4,
        )

        cpu_pct = 0.0
        ram_mb = 0.0
        try:
            proc = psutil.Process()
            cpu_pct = proc.cpu_percent()
            ram_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            pass

        staging_db = Path("data/processed/staging.duckdb")
        db_size_mb = (staging_db.stat().st_size / (1024 * 1024)) if staging_db.exists() else 0.0

        total_items = sum(s.get("items", 0) for s in self.step_metadata.values())
        throughput = (total_items / elapsed) if elapsed > 0 else 0.0

        self.telemetry_panel.update_telemetry(
            cpu_pct=cpu_pct,
            ram_mb=ram_mb,
            db_size_mb=db_size_mb,
            throughput=throughput,
        )

    @work(thread=True)
    def run_worker_in_background(self) -> None:
        if self._worker_func:
            try:
                self._worker_func()
            except Exception as e:
                logger.error("Pipeline worker crashed: %s", e)
            finally:
                self._safe_call(self._restore_logging)
                self._safe_call(self.header_widget.update_status, "COMPLETED", time.time() - self.start_time)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._restore_logging()

    def action_toggle_pause(self) -> None:
        self.is_paused = not self.is_paused

    def action_refresh_view(self) -> None:
        self.refresh()

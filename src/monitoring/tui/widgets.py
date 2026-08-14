"""
Modular Terminal User Interface (TUI) Widgets for Pipeline Monitoring.
"""

from typing import Any, Dict, List, Optional
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, RichLog, Static


class HeaderWidget(Static):
    """Header widget displaying pipeline title, status, elapsed time, and worker count."""

    DEFAULT_CSS = """
    HeaderWidget {
        dock: top;
        height: 3;
        background: $primary-darken-2;
        color: $text;
        content-align: center middle;
        padding: 0 1;
    }
    """

    def __init__(self, title: str = "VOCAB CRAFT ENGINE - PIPELINE MONITOR", **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.status = "IDLE"
        self.elapsed_seconds = 0.0
        self.worker_count = 1
        self.elapsed_str = "00:00:00"

    def update_status(self, status: str, elapsed: float, workers: int = 1) -> None:
        self.status = status
        self.elapsed_seconds = elapsed
        self.worker_count = workers
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        self.elapsed_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        self.update(
            f"[bold cyan]▶ {self.title}[/bold cyan] | "
            f"Status: [bold green]{self.status}[/bold green] | "
            f"Elapsed: [yellow]{self.elapsed_str}[/yellow] | "
            f"Workers: [magenta]{self.worker_count}[/magenta]"
        )


class StepListWidget(Widget):
    """Widget displaying step execution table with real-time status and metrics."""

    DEFAULT_CSS = """
    StepListWidget {
        height: auto;
        min-height: 8;
        max-height: 55%;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.steps_data: Dict[str, Dict[str, Any]] = {}
        self._table = DataTable(id="steps_table")

    def compose(self) -> ComposeResult:
        yield self._table

    def on_mount(self) -> None:
        self._table.add_columns("#", "Step Name", "Status", "Time (s)", "Items", "Retries", "Metrics")
        for idx, (name, data) in enumerate(self.steps_data.items(), 1):
            self._table.add_row(
                str(idx),
                name,
                "PENDING ⏸",
                "-",
                "0",
                "0",
                "",
                key=name,
            )

    def init_steps(self, step_names: List[str]) -> None:
        for name in step_names:
            self.steps_data[name] = {
                "status": "PENDING",
                "duration": 0.0,
                "items": 0,
                "retries": 0,
                "metrics": "",
            }

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics: str = "",
    ) -> None:
        if step_name not in self.steps_data:
            self.steps_data[step_name] = {}
        self.steps_data[step_name].update({
            "status": status,
            "duration": duration,
            "items": items,
            "retries": retries,
            "metrics": metrics,
        })
        if self._table.row_count > 0:
            status_badge = {
                "PENDING": "PENDING ⏸",
                "RUNNING": "[bold cyan]RUNNING ⏳[/bold cyan]",
                "SUCCESS": "[bold green]SUCCESS ✅[/bold green]",
                "FAILED": "[bold red]FAILED ❌[/bold red]",
                "SKIPPED": "[dim]SKIPPED ⏭[/dim]",
            }.get(status, status)
            try:
                self._table.update_cell(step_name, "Status", status_badge)
                self._table.update_cell(step_name, "Time (s)", f"{duration:.1f}s" if duration > 0 else "-")
                self._table.update_cell(step_name, "Items", f"{items:,}" if items > 0 else "0")
                self._table.update_cell(step_name, "Retries", str(retries))
                self._table.update_cell(step_name, "Metrics", metrics)
            except Exception:
                pass


class MetricsCard(Static):
    """Widget displaying system resources and throughput telemetry."""

    DEFAULT_CSS = """
    MetricsCard {
        height: auto;
        padding: 0 1;
        background: $surface;
        border: solid $accent;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cpu_pct = 0.0
        self.memory_mb = 0.0
        self.db_size_mb = 0.0
        self.throughput = 0.0
        self.eta_sec = 0.0
        self.eta_str = "--:--:--"

    def update_metrics(
        self,
        cpu_pct: float,
        memory_mb: float,
        db_size_mb: float,
        throughput: float,
        eta_sec: float,
    ) -> None:
        self.cpu_pct = cpu_pct
        self.memory_mb = memory_mb
        self.db_size_mb = db_size_mb
        self.throughput = throughput
        self.eta_sec = eta_sec
        mins, secs = divmod(int(eta_sec), 60)
        hours, mins = divmod(mins, 60)
        self.eta_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if eta_sec > 0 else "--:--:--"
        self.update(
            f"[bold]Telemetry:[/bold] CPU: [cyan]{cpu_pct:.1f}%[/cyan] | "
            f"RAM: [cyan]{memory_mb:.0f} MB[/cyan] | "
            f"DB Size: [cyan]{db_size_mb:.1f} MB[/cyan] | "
            f"Speed: [green]{throughput:,.0f} items/s[/green] | "
            f"ETA: [yellow]{self.eta_str}[/yellow]"
        )


class LogStreamWidget(RichLog):
    """Widget displaying live auto-scrolling execution logs."""

    DEFAULT_CSS = """
    LogStreamWidget {
        height: 1fr;
        margin-top: 1;
        border: solid $primary;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, **kwargs)

    def write_log(self, message: str) -> None:
        self.write(message)

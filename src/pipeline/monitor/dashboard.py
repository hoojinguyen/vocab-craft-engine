import sys
import time
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text


class RichPipelineDashboard:
    """Real-time Terminal UI dashboard for monitoring pipeline execution using Rich."""

    def __init__(self, enabled: bool = True, title: str = "VOCAB CRAFT ENGINE - PIPELINE MONITOR"):
        self.console = Console()
        self.enabled = enabled and self.console.is_terminal
        self.title = title
        self.is_active = False
        self.live: Optional[Live] = None
        self.steps_data: Dict[str, Dict[str, Any]] = {}
        self.logs_buffer: List[str] = []
        self.start_time = time.time()

    def set_steps(self, step_names: List[str]) -> None:
        """Initialize the map of pipeline steps to track."""
        for name in step_names:
            self.steps_data[name] = {
                "status": "PENDING",
                "duration": 0.0,
                "items": 0,
                "retries": 0,
                "metrics": ""
            }

    def start(self) -> None:
        """Begin live rendering if enabled and attached to a TTY."""
        if not self.enabled:
            return
        self.is_active = True
        self.start_time = time.time()
        self.live = Live(
            self._generate_layout(),
            console=self.console,
            refresh_per_second=8,
            auto_refresh=True
        )
        self.live.start()

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics_str: str = ""
    ) -> None:
        """Update step progress, execution state, and metrics."""
        if step_name not in self.steps_data:
            self.steps_data[step_name] = {}

        self.steps_data[step_name].update({
            "status": status,
            "duration": duration,
            "items": items,
            "retries": retries,
            "metrics": metrics_str
        })
        if self.live and self.is_active:
            self.live.update(self._generate_layout())

    def add_log(self, log_line: str) -> None:
        """Append a log line to the live log stream buffer (max 10 lines)."""
        self.logs_buffer.append(log_line)
        if len(self.logs_buffer) > 10:
            self.logs_buffer.pop(0)
        if self.live and self.is_active:
            self.live.update(self._generate_layout())

    def _generate_layout(self) -> Layout:
        """Construct a 3-part layout (Header Panel, Steps Table, Live Logs Stream)."""
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body", ratio=2),
            Layout(name="footer", size=8)
        )

        elapsed = round(time.time() - self.start_time, 1)
        completed = sum(1 for s in self.steps_data.values() if s.get("status") in ("SUCCESS", "SKIPPED"))
        total = len(self.steps_data)

        header_text = f"🚀 {self.title} | Elapsed: {elapsed}s | Completed: {completed}/{total}"
        layout["header"].update(Panel(Text(header_text, style="bold cyan"), style="blue"))

        table = Table(expand=True, box=None)
        table.add_column("#", style="dim", width=4)
        table.add_column("Step Name", style="bold white", width=25)
        table.add_column("Status", width=15)
        table.add_column("Time (s)", justify="right", width=10)
        table.add_column("Items", justify="right", width=10)
        table.add_column("Retries", justify="right", width=8)
        table.add_column("Metrics", style="dim", width=20)

        for idx, (name, data) in enumerate(self.steps_data.items(), 1):
            st = data.get("status", "PENDING")
            if st == "SUCCESS":
                status_cell = Text("SUCCESS", style="bold green")
            elif st == "FAILED":
                status_cell = Text("FAILED ✖", style="bold red")
            elif st == "RUNNING":
                status_cell = Text("RUNNING ⏳", style="bold cyan")
            elif "RETRY" in st:
                status_cell = Text(st, style="bold yellow")
            elif st == "SKIPPED":
                status_cell = Text("SKIPPED ⏭", style="dim white")
            else:
                status_cell = Text("PENDING ⏸", style="dim")

            table.add_row(
                str(idx),
                name,
                status_cell,
                f"{data.get('duration', 0.0):.2f}s",
                f"{data.get('items', 0):,}",
                str(data.get('retries', 0)),
                str(data.get('metrics', ""))
            )

        layout["body"].update(Panel(table, title="Pipeline Steps Overview", style="white"))

        log_text = "\n".join(self.logs_buffer) if self.logs_buffer else "Initializing pipeline..."
        layout["footer"].update(Panel(log_text, title="📜 Live Logs Stream", style="grey70"))

        return layout

    def stop(self) -> None:
        """Gracefully stop the Live renderer."""
        if self.live and self.is_active:
            self.live.stop()
        self.is_active = False

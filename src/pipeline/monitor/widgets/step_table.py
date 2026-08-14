from typing import Any, Dict, List, Optional
from textual.widgets import DataTable


def make_progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "[dim]--[/dim]"
    ratio = min(1.0, max(0.0, current / total))
    filled = int(round(ratio * width))
    empty = width - filled
    pct = int(ratio * 100)
    return f"[cyan]{'█' * filled}[/cyan][dim]{'▒' * empty}[/dim] {pct:>3d}%"


class StepTable(DataTable):
    """Interactive DataTable showing step progress, elapsed time, items, and ETA."""

    DEFAULT_CSS = """
    StepTable {
        height: 50%;
        border-bottom: solid #45475a;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(id="step_table", cursor_type="row", **kwargs)
        self.steps_data: Dict[str, Dict[str, Any]] = {}

    def on_mount(self) -> None:
        self.add_column("#", key="idx", width=3)
        self.add_column("Step Name", key="name", width=22)
        self.add_column("Status", key="status", width=12)
        self.add_column("Progress", key="progress", width=18)
        self.add_column("Time", key="time", width=8)
        self.add_column("Items", key="items", width=10)
        self.add_column("ETA", key="eta", width=8)
        if self.steps_data and self.row_count == 0:
            for idx, name in enumerate(self.steps_data.keys(), 1):
                self.add_row(
                    str(idx),
                    name,
                    "[dim]PENDING[/dim]",
                    "[dim]--[/dim]",
                    "-",
                    "0",
                    "-",
                    key=name,
                )

    def init_steps(self, step_names: List[str]) -> None:
        for name in step_names:
            self.steps_data[name] = {
                "status": "PENDING",
                "current": 0,
                "total": 0,
                "duration": 0.0,
                "items": 0,
                "retries": 0,
                "eta": "-",
            }
        if self.is_mounted and self.row_count == 0:
            for idx, name in enumerate(step_names, 1):
                self.add_row(
                    str(idx),
                    name,
                    "[dim]PENDING[/dim]",
                    "[dim]--[/dim]",
                    "-",
                    "0",
                    "-",
                    key=name,
                )

    def update_step_progress(self, step_name: str, current: int, total: int, message: str = "") -> None:
        if step_name in self.steps_data:
            self.steps_data[step_name]["current"] = current
            self.steps_data[step_name]["total"] = total
            self.steps_data[step_name]["items"] = current
            bar = make_progress_bar(current, total)
            try:
                self.update_cell(step_name, "progress", bar)
                self.update_cell(step_name, "items", f"{current:,}")
            except Exception:
                pass

    def update_step_status(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        eta: str = "-",
    ) -> None:
        if step_name not in self.steps_data:
            self.steps_data[step_name] = {}
        self.steps_data[step_name].update({
            "status": status,
            "duration": duration,
            "items": items,
            "retries": retries,
            "eta": eta,
        })
        status_badge = {
            "PENDING": "[dim]PENDING ⏸[/dim]",
            "RUNNING": "[bold cyan]RUNNING ⏳[/bold cyan]",
            "SUCCESS": "[bold green]SUCCESS ✔[/bold green]",
            "FAILED": "[bold red]FAILED ✖[/bold red]",
            "SKIPPED": "[dim yellow]SKIPPED ⊘[/dim yellow]",
        }.get(status, status)

        try:
            self.update_cell(step_name, "status", status_badge)
            self.update_cell(step_name, "time", f"{duration:.1f}s" if duration > 0 else "-")
            if items > 0:
                self.update_cell(step_name, "items", f"{items:,}")
            self.update_cell(step_name, "eta", eta)
            if status == "SUCCESS":
                self.update_cell(step_name, "progress", "[bold green]██████████ 100%[/bold green]")
        except Exception:
            pass

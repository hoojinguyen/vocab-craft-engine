from textual.widgets import Static


class HeaderWidget(Static):
    """Header bar showing pipeline title, status, runtime, and worker metrics."""

    DEFAULT_CSS = """
    HeaderWidget {
        dock: top;
        height: 3;
        background: #1e1e2e;
        color: #cdd6f4;
        content-align: center middle;
        padding: 0 1;
        border-bottom: heavy #89b4fa;
    }
    """

    def __init__(self, title: str = "VOCAB CRAFT ENGINE — PIPELINE MONITOR V2", **kwargs):
        super().__init__(**kwargs)
        self.title_str = title
        self.status = "IDLE"
        self.elapsed_seconds = 0.0
        self.worker_count = 4
        self.current_level = "1/5"

    def update_status(self, status: str, elapsed: float, workers: int = 4, level: str = "1/5") -> None:
        self.status = status
        self.elapsed_seconds = elapsed
        self.worker_count = workers
        self.current_level = level

        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"

        status_color = {
            "RUNNING": "bold cyan",
            "COMPLETED": "bold green",
            "FAILED": "bold red",
            "PAUSED": "bold yellow",
            "IDLE": "dim",
        }.get(status, "bold white")

        self.update(
            f"[bold #89b4fa]▶ {self.title_str}[/bold #89b4fa] | "
            f"Status: [{status_color}]{self.status}[/{status_color}] | "
            f"Elapsed: [yellow]{time_str}[/yellow] | "
            f"Level: [magenta]{self.current_level}[/magenta] | "
            f"Workers: [blue]{self.worker_count}[/blue]"
        )

from typing import Dict, List
from textual.widgets import Static


class DAGPanel(Static):
    """Renders ASCII dependency tree with live node status color indicators."""

    DEFAULT_CSS = """
    DAGPanel {
        width: 32;
        height: 100%;
        border-right: solid #45475a;
        background: #181825;
        padding: 0 1;
    }
    """

    STATUS_ICONS = {
        "PENDING": "[dim]○[/dim]",
        "RUNNING": "[bold cyan]●[/bold cyan]",
        "SUCCESS": "[bold green]✔[/bold green]",
        "FAILED": "[bold red]✖[/bold red]",
        "SKIPPED": "[dim yellow]⊘[/dim yellow]",
        "RETRYING": "[bold yellow]◌[/bold yellow]",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.levels: List[List[str]] = []
        self.nodes: Dict[str, str] = {}

    def init_dag(self, execution_levels: List[List[str]]) -> None:
        self.levels = execution_levels
        for level in self.levels:
            for step_name in level:
                self.nodes[step_name] = "PENDING"
        self._refresh_tree()

    def update_node_status(self, step_name: str, status: str) -> None:
        if step_name in self.nodes:
            self.nodes[step_name] = status
            self._refresh_tree()

    def _refresh_tree(self) -> None:
        lines = ["[bold underline #89b4fa]DAG EXECUTION GRAPH[/bold underline #89b4fa]\n"]
        level_names = ["1: Ingest Init", "2: Ingest Sources", "3: Transform", "4: Enrichment", "5: Export"]

        for idx, level in enumerate(self.levels):
            name = level_names[idx] if idx < len(level_names) else f"Level {idx+1}"
            lines.append(f"[bold #fab387]▼ {name}[/bold #fab387]")
            for step in level:
                status = self.nodes.get(step, "PENDING")
                icon = self.STATUS_ICONS.get(status, "○")
                step_display = f"  {icon} [white]{step}[/white]" if status == "RUNNING" else f"  {icon} [dim]{step}[/dim]" if status in ("PENDING", "SKIPPED") else f"  {icon} {step}"
                lines.append(step_display)
            lines.append("")

        self.update("\n".join(lines))

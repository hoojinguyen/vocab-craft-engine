from typing import Any, Dict, Optional
from textual.widgets import Static


class StepDetailWidget(Static):
    """Inspector panel displaying in-depth metadata for the highlighted step."""

    DEFAULT_CSS = """
    StepDetailWidget {
        height: 6;
        border-bottom: solid #45475a;
        background: #181825;
        padding: 0 1;
    }
    """

    def format_step_detail(self, data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return "[dim]Select a step above to inspect execution parameters and outputs.[/dim]"

        name = data.get("name", "Unknown")
        status = data.get("status", "PENDING")
        desc = data.get("description", "No description")
        exec_type = data.get("type", "cpu").upper()
        deps = data.get("depends_on", "None")
        prods = data.get("produces", "None")
        items = data.get("items", 0)
        dur = data.get("duration", 0.0)
        retries = data.get("retries", 0)
        err = data.get("error", "")

        err_text = f" | [bold red]Error:[/bold red] {err}" if err else ""

        return (
            f"[bold #89b4fa]▶ Step Detail:[/bold #89b4fa] [bold white]{name}[/bold white] "
            f"([{ 'bold green' if status=='SUCCESS' else 'bold cyan' if status=='RUNNING' else 'dim' }]{status}[/]) "
            f"| [yellow]{desc}[/yellow]\n"
            f"[dim]Type:[/dim] {exec_type} | [dim]Depends on:[/dim] {deps} | [dim]Produces:[/dim] [cyan]{prods}[/cyan]\n"
            f"[dim]Processed:[/dim] [green]{items:,} rows[/green] | [dim]Time:[/dim] {dur:.2f}s | [dim]Retries:[/dim] {retries}{err_text}"
        )

    def display_step(self, data: Optional[Dict[str, Any]]) -> None:
        self.update(self.format_step_detail(data))

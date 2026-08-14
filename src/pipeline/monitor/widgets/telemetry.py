from textual.widgets import Static


class TelemetryPanel(Static):
    """Footer telemetry panel showing resource consumption and translation metrics."""

    DEFAULT_CSS = """
    TelemetryPanel {
        dock: bottom;
        height: 3;
        background: #181825;
        border-top: heavy #89b4fa;
        padding: 0 1;
    }
    """

    def update_telemetry(
        self,
        cpu_pct: float = 0.0,
        ram_mb: float = 0.0,
        db_size_mb: float = 0.0,
        throughput: float = 0.0,
        cache_hits: int = 0,
        argos_count: int = 0,
        google_count: int = 0,
    ) -> None:
        total_trans = cache_hits + argos_count + google_count
        cache_ratio = (cache_hits / total_trans * 100) if total_trans > 0 else 0.0
        argos_ratio = (argos_count / total_trans * 100) if total_trans > 0 else 0.0
        google_ratio = (google_count / total_trans * 100) if total_trans > 0 else 0.0

        line1 = (
            f"[bold #89b4fa]SYSTEM:[/bold #89b4fa] CPU: [cyan]{cpu_pct:4.1f}%[/cyan] | "
            f"RAM: [cyan]{ram_mb:5.0f} MB[/cyan] | "
            f"DuckDB: [cyan]{db_size_mb:5.1f} MB[/cyan] | "
            f"Speed: [green]{throughput:8,.0f} rows/s[/green]"
        )
        line2 = (
            f"[bold #fab387]TRANSLATION:[/bold #fab387] Cache Hits: [green]{cache_ratio:4.1f}%[/green] | "
            f"Argos (Offline): [blue]{argos_ratio:4.1f}%[/blue] | "
            f"Google (Fallback): [yellow]{google_ratio:4.1f}%[/yellow] ({google_count:,} reqs)"
        )
        self.update(f"{line1}\n{line2}")

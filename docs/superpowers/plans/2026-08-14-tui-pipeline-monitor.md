# TUI Dashboard & Live DAG Pipeline Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive, comprehensive Terminal UI (TUI) dashboard using Textual featuring DAG ASCII graph visualization, inline progress bars with ETA, interactive step detail inspector, and system/translation telemetry.

**Architecture:** A modular Textual application (`src/pipeline/monitor/`) consisting of distinct widgets (`DAGPanel`, `StepTable`, `StepDetail`, `TelemetryPanel`, `LogStreamWidget`) synchronized with the pipeline orchestrator via a thread-safe, throttled `ProgressReporter` protocol.

**Tech Stack:** Python 3.11+, Textual, Rich, psutil, DuckDB, PyArrow, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-tui-pipeline-monitor-design.md`

## Global Constraints

- Must run flawlessly on Python >= 3.11 with `textual>=0.70.0`, `rich>=13.7.0`, `psutil>=5.9.0`.
- All updates from worker threads to Textual UI must use `call_from_thread()` to maintain thread safety.
- Progress reporting must be throttled (<= 10 updates/sec per step) to prevent UI freezing on high-throughput data streams.
- Headless execution with `--no-tui` must continue to work cleanly without initializing Textual.
- Maintain 100% pass rate across the full pytest suite.

---

### Task 1: ProgressReporter Protocol & PipelineContext Integration

**Files:**
- Create: `src/pipeline/monitor/progress.py`
- Modify: `src/pipeline/core/context.py`
- Test: `tests/test_pipeline/test_progress_reporter.py`

**Interfaces:**
- Consumes: None
- Produces:
  - `ProgressReporter(callback: Callable[[str, int, int, str], None])`
  - `StepProgress(step_name: str, total: int, reporter: ProgressReporter)` with `advance(count)` and `track_batch(count)`
  - `PipelineContext.create_progress(step_name: str, total: int) -> StepProgress`

- [ ] **Step 1: Write the failing unit tests for ProgressReporter**

Create `tests/test_pipeline/test_progress_reporter.py`:
```python
import time
from src.pipeline.monitor.progress import ProgressReporter, StepProgress
from src.pipeline.core.context import PipelineContext
from src.db.duckdb_manager import DuckDBManager


def test_progress_reporter_emission():
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.0)
    step_prog = StepProgress(step_name="test_step", total=100, reporter=reporter)

    step_prog.advance(25, "Processing batch 1")
    step_prog.advance(25, "Processing batch 2")

    assert len(events) == 2
    assert events[0] == ("test_step", 25, 100, "Processing batch 1")
    assert events[1] == ("test_step", 50, 100, "Processing batch 2")


def test_progress_reporter_context_manager(tmp_path):
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.0)
    db_mgr = DuckDBManager(tmp_path / "test.duckdb")
    ctx = PipelineContext(db_manager=db_mgr, progress_reporter=reporter)

    prog = ctx.create_progress("ingest_test", total=1000)
    with prog.track_batch(200):
        pass

    assert prog.current == 200
    assert len(events) == 1
    assert events[0] == ("ingest_test", 200, 1000, "")
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline/test_progress_reporter.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProgressReporter'`

- [ ] **Step 3: Implement ProgressReporter & update PipelineContext**

Create `src/pipeline/monitor/progress.py`:
```python
"""Thread-safe Progress Reporter Protocol for Pipeline Steps."""

import time
from typing import Callable, Optional


class ProgressReporter:
    """Dispatches progress updates with throttling to avoid UI event spam."""

    def __init__(
        self,
        callback: Optional[Callable[[str, int, int, str], None]] = None,
        throttle_interval: float = 0.08,
    ):
        self.callback = callback
        self.throttle_interval = throttle_interval
        self._last_emitted: dict[str, float] = {}

    def emit_progress(self, step_name: str, current: int, total: int, message: str = "") -> None:
        if not self.callback:
            return

        now = time.monotonic()
        last_time = self._last_emitted.get(step_name, 0.0)

        # Always emit on 0, completion, or when throttle interval has elapsed
        if current >= total or current == 0 or (now - last_time) >= self.throttle_interval:
            self._last_emitted[step_name] = now
            self.callback(step_name, current, total, message)


class StepProgress:
    """Tracks progress for an individual pipeline step."""

    def __init__(self, step_name: str, total: int, reporter: Optional[ProgressReporter] = None):
        self.step_name = step_name
        self.total = max(1, total)
        self.current = 0
        self.reporter = reporter

    def advance(self, count: int = 1, message: str = "") -> None:
        self.current = min(self.total, self.current + count)
        if self.reporter:
            self.reporter.emit_progress(self.step_name, self.current, self.total, message)

    def track_batch(self, count: int, message: str = ""):
        """Context manager to auto-advance progress when a batch completes."""
        step = self

        class BatchContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    step.advance(count, message)

        return BatchContext()
```

Modify `src/pipeline/core/context.py` to add `progress_reporter` field and `create_progress` method:
```python
@dataclass
class PipelineContext:
    db_manager: Union[DuckDBManager, DatabaseManager]
    args: Any = None
    output_dir: Optional[Path] = None
    enabled_optional_steps: List[str] = field(default_factory=list)
    shared_data: Dict[str, Any] = field(default_factory=dict)
    progress_reporter: Optional[Any] = None

    def create_progress(self, step_name: str, total: int = 100) -> Any:
        from src.pipeline.monitor.progress import StepProgress
        return StepProgress(step_name=step_name, total=total, reporter=self.progress_reporter)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline/test_progress_reporter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/monitor/progress.py src/pipeline/core/context.py tests/test_pipeline/test_progress_reporter.py
git commit -m "feat(monitor): add ProgressReporter protocol and PipelineContext integration"
```

---

### Task 2: Modular TUI Widgets (`DAGPanel`, `StepTable`, `StepDetail`, `TelemetryPanel`, `LogStream`)

**Files:**
- Create:
  - `src/pipeline/monitor/widgets/__init__.py`
  - `src/pipeline/monitor/widgets/header.py`
  - `src/pipeline/monitor/widgets/dag_panel.py`
  - `src/pipeline/monitor/widgets/step_table.py`
  - `src/pipeline/monitor/widgets/step_detail.py`
  - `src/pipeline/monitor/widgets/telemetry.py`
  - `src/pipeline/monitor/widgets/log_stream.py`
- Test: `tests/test_pipeline/test_tui_widgets.py`

**Interfaces:**
- Consumes: `DAG` from `src.pipeline.core.dag`
- Produces:
  - `HeaderWidget(title: str)` with `update_status(...)`
  - `DAGPanel()` with `init_dag(levels)` and `update_node_status(name, status)`
  - `StepTable()` with `init_steps(names)`, `update_step_progress(name, current, total)`, `update_step_status(...)`
  - `StepDetailWidget()` with `display_step(data_dict)`
  - `TelemetryPanel()` with `update_telemetry(cpu, mem, db_size, speed, cache_stats)`
  - `LogStreamWidget()` with `write_log(message)`

- [ ] **Step 1: Write unit tests for TUI Widgets**

Create `tests/test_pipeline/test_tui_widgets.py`:
```python
from src.pipeline.monitor.widgets.dag_panel import DAGPanel
from src.pipeline.monitor.widgets.step_table import StepTable, make_progress_bar
from src.pipeline.monitor.widgets.step_detail import StepDetailWidget
from src.pipeline.monitor.widgets.telemetry import TelemetryPanel


def test_make_progress_bar():
    bar_0 = make_progress_bar(0, 100, width=10)
    assert "0%" in bar_0
    bar_50 = make_progress_bar(50, 100, width=10)
    assert "50%" in bar_50
    bar_100 = make_progress_bar(100, 100, width=10)
    assert "100%" in bar_100


def test_dag_panel_structure():
    panel = DAGPanel()
    mock_levels = [["schema_init"], ["ingest_kaikki", "ingest_tatoeba"]]
    panel.init_dag(mock_levels)
    assert "schema_init" in panel.nodes
    assert "ingest_kaikki" in panel.nodes


def test_step_detail_display():
    detail = StepDetailWidget()
    sample_data = {
        "name": "ingest_kaikki",
        "status": "RUNNING",
        "description": "Ingest Kaikki Wiktionary",
        "type": "cpu",
        "depends_on": "schema_init",
        "produces": "words, definitions",
        "items": 12500,
        "duration": 4.5,
        "retries": 0,
        "error": "",
    }
    rendered = detail.format_step_detail(sample_data)
    assert "ingest_kaikki" in rendered
    assert "words, definitions" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline/test_tui_widgets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pipeline.monitor.widgets'`

- [ ] **Step 3: Implement the Modular TUI Widgets**

Create `src/pipeline/monitor/widgets/__init__.py`:
```python
from .dag_panel import DAGPanel
from .header import HeaderWidget
from .log_stream import LogStreamWidget
from .step_detail import StepDetailWidget
from .step_table import StepTable
from .telemetry import TelemetryPanel

__all__ = [
    "HeaderWidget",
    "DAGPanel",
    "StepTable",
    "StepDetailWidget",
    "TelemetryPanel",
    "LogStreamWidget",
]
```

Create `src/pipeline/monitor/widgets/header.py`:
```python
from textual.widget import Widget
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
```

Create `src/pipeline/monitor/widgets/dag_panel.py`:
```python
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
```

Create `src/pipeline/monitor/widgets/step_table.py`:
```python
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
```

Create `src/pipeline/monitor/widgets/step_detail.py`:
```python
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
```

Create `src/pipeline/monitor/widgets/telemetry.py`:
```python
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
```

Create `src/pipeline/monitor/widgets/log_stream.py`:
```python
from textual.widgets import RichLog


class LogStreamWidget(RichLog):
    """Auto-scrolling live logs viewer with Rich markup support."""

    DEFAULT_CSS = """
    LogStreamWidget {
        height: 1fr;
        background: #11111b;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, **kwargs)

    def write_log(self, message: str) -> None:
        self.write(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline/test_tui_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/monitor/widgets/ tests/test_pipeline/test_tui_widgets.py
git commit -m "feat(monitor): add modular TUI widgets (DAGPanel, StepTable, StepDetail, TelemetryPanel, LogStream)"
```

---

### Task 3: Pipeline Dashboard App (`dashboard.py`) & User Interaction

**Files:**
- Modify: `src/pipeline/monitor/dashboard.py`
- Test: `tests/test_pipeline/test_tui_dashboard.py`

**Interfaces:**
- Consumes: All widgets from `src.pipeline.monitor.widgets`
- Produces: `TextualPipelineDashboard` class implementing `App` with worker background execution, step selection events, pause/resume, and logging redirection.

- [ ] **Step 1: Write unit tests for Pipeline Dashboard App**

Create `tests/test_pipeline/test_tui_dashboard.py`:
```python
import pytest
from src.pipeline.monitor.dashboard import TextualPipelineDashboard


def test_dashboard_initialization():
    app = TextualPipelineDashboard(enabled=False)
    app.set_dag_levels([["schema_init"], ["ingest_kaikki"]])
    assert "schema_init" in app.step_metadata
    assert "ingest_kaikki" in app.step_metadata


def test_dashboard_step_updates():
    app = TextualPipelineDashboard(enabled=False)
    app.set_dag_levels([["schema_init"]])
    app.update_step("schema_init", "RUNNING")
    assert app.step_metadata["schema_init"]["status"] == "RUNNING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline/test_tui_dashboard.py -v`
Expected: FAIL

- [ ] **Step 3: Implement TextualPipelineDashboard in `dashboard.py`**

Rewrite `src/pipeline/monitor/dashboard.py`:
```python
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
from textual.containers import Container, Horizontal, Vertical
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
        self.start_time = time.time()
        self.is_paused = False

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
            self.step_metadata[step_name] = {
                "name": step_name,
                "status": "PENDING",
                "description": info.get("description", ""),
                "type": info.get("type", "cpu"),
                "depends_on": ", ".join(info.get("depends_on", [])) or "None",
                "produces": ", ".join(info.get("produces", [])) or "None",
                "items": 0,
                "duration": 0.0,
                "retries": 0,
                "error": "",
            }
        if all_steps and not self.selected_step_name:
            self.selected_step_name = all_steps[0]

    def set_steps(self, step_names: List[str]) -> None:
        """Compatibility helper."""
        self.set_dag_levels([[s] for s in step_names])

    def set_worker(self, worker_func: Callable[[], None]) -> None:
        self._worker_func = worker_func

    def add_log(self, message: str) -> None:
        if self.is_running:
            self.call_from_thread(self.log_stream.write_log, message)

    def update_step(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        error_or_metrics: str = "",
    ) -> None:
        if step_name in self.step_metadata:
            self.step_metadata[step_name].update({
                "status": status,
                "duration": duration,
                "items": items,
                "retries": retries,
                "error": error_or_metrics if "FAIL" in status else "",
            })

        if self.is_running:
            self.call_from_thread(self.dag_panel.update_node_status, step_name, status)
            self.call_from_thread(
                self.step_table.update_step_status, step_name, status, duration, items, retries
            )
            if self.selected_step_name == step_name:
                self.call_from_thread(
                    self.step_detail.display_step, self.step_metadata[step_name]
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

    def _setup_logging_redirection(self) -> None:
        root_logger = logging.getLogger()
        self.logging_handler = DashboardLoggingHandler(self)
        self.logging_handler.setLevel(logging.INFO)
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
                self.call_from_thread(self._restore_logging)
                self.call_from_thread(self.header_widget.update_status, "COMPLETED", time.time() - self.start_time)

    def start(self) -> None: pass
    def stop(self) -> None: self._restore_logging()
    def action_toggle_pause(self) -> None: self.is_paused = not self.is_paused
    def action_refresh_view(self) -> None: self.refresh()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline/test_tui_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/monitor/dashboard.py tests/test_pipeline/test_tui_dashboard.py
git commit -m "feat(monitor): rewrite TextualPipelineDashboard with 2-column DAG layout and interactive inspector"
```

---

### Task 4: Orchestrator Integration & Streaming Progress in Steps

**Files:**
- Modify: `src/pipeline/core/orchestrator.py`
- Modify: `src/ingestion/kaikki_ingestor.py`
- Modify: `src/ingestion/opus_ingestor.py`
- Modify: `src/enrichment/translation.py`
- Test: `tests/test_pipeline/test_orchestrator.py`

**Interfaces:**
- Consumes: `ProgressReporter` from `src.pipeline.monitor.progress`
- Produces: Live streaming progress updates from `KaikkiIngestor`, `OpusIngestor`, and `HybridTranslator` directly to `StepTable` in TUI.

- [ ] **Step 1: Write integration tests for Orchestrator with TUI and ProgressReporter**

Create test case in `tests/test_pipeline/test_orchestrator_progress.py`:
```python
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry
from src.pipeline.core.context import PipelineContext
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.monitor.progress import ProgressReporter


def test_orchestrator_initializes_progress_reporter(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "orch_test.duckdb")
    db_mgr.init_schema()

    progress_events = []
    def on_prog(name, cur, tot, msg):
        progress_events.append((name, cur, tot))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    ctx = PipelineContext(db_manager=db_mgr, progress_reporter=reporter)

    registry = get_default_registry()
    orch = PipelineOrchestrator(registry=registry)
    orch._execute_single_step(
        registry.get_step("schema_init"), ctx, dry_run=True, force_all=False, force_steps=set(), retry_policy=None
    )
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify behavior**

Run: `.venv/bin/pytest tests/test_pipeline/test_orchestrator_progress.py -v`

- [ ] **Step 3: Update Orchestrator & Ingest Steps to stream progress**

In `src/pipeline/core/orchestrator.py`:
- Initialize `ProgressReporter` connected to `self.dashboard.step_table.update_step_progress` and attach to `context.progress_reporter`.
- Pass step metadata map (`description`, `depends_on`, `produces`, `execution_type`) to `dashboard.set_dag_levels()`.

In `src/ingestion/kaikki_ingestor.py`, `src/ingestion/opus_ingestor.py`, `src/enrichment/translation.py`:
- Accept optional `progress` reporter from context to advance progress count during batch stream.

- [ ] **Step 4: Run full test suite to verify 100% pass**

Run: `.venv/bin/pytest -v`
Expected: 243+ passed, 0 failed

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/orchestrator.py src/ingestion/ tests/test_pipeline/test_orchestrator_progress.py
git commit -m "feat(orchestrator): integrate live ProgressReporter and step streaming telemetry into TUI"
```

---

## Verification Plan

### Automated Tests
```bash
# Unit tests for progress reporter and TUI widgets
pytest tests/test_pipeline/test_progress_reporter.py -v
pytest tests/test_pipeline/test_tui_widgets.py -v
pytest tests/test_pipeline/test_tui_dashboard.py -v
pytest tests/test_pipeline/test_orchestrator_progress.py -v

# Full suite regression check
pytest -v
```

### Manual Verification
1. Run `make dry-run` to preview the DAG plan in console.
2. Run `make run-tui` and verify:
   - Left pane renders ASCII DAG tree with active node highlighting.
   - StepTable shows real-time progress bars and throughput.
   - Selecting a row updates the StepDetail inspector card.
   - Pressing `q` exits cleanly and restores terminal logging without corruption.

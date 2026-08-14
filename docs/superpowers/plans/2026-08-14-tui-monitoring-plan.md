# Terminal UI (TUI) Monitoring Module Implementation Plan (Phase 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement modular Textual TUI widgets in `src/monitoring/tui/widgets.py` and the main application controller in `src/monitoring/tui/progress.py`, ensuring full backward compatibility with `src/pipeline/monitor/dashboard.py`.

**Architecture:** `widgets.py` encapsulates `HeaderWidget`, `StepListWidget`, `MetricsCard`, and `LogStreamWidget`; `progress.py` houses `PipelineProgressApp` and `TUILoggingHandler` with reactive polling and interactive keybindings; `dashboard.py` aliases the new implementation to prevent regressions across existing tests.

**Tech Stack:** Python 3.14, Textual, Rich, PyTest, PyTest-Asyncio.

**Spec:** `docs/superpowers/specs/2026-08-14-tui-monitoring-design.md`

## Global Constraints

- Python version: Python 3.14 (.venv)
- Use standard Textual and Rich widgets and markup
- Zero regressions on existing pipeline tests (`test_orchestrator.py`, etc.)
- Full backward compatibility alias in `src/pipeline/monitor/dashboard.py`
- Strict adherence to TDD: Test -> Fail -> Implement -> Pass -> Commit

---

### Task 1: Implement Modular TUI Widgets (`src/monitoring/tui/widgets.py`)

**Files:**
- Create: `src/monitoring/__init__.py`
- Create: `src/monitoring/tui/__init__.py`
- Create: `src/monitoring/tui/widgets.py`
- Create: `tests/test_monitoring/test_tui_widgets.py`

**Interfaces:**
- `HeaderWidget`: `update_status(status: str, elapsed: float, workers: int)`
- `StepListWidget`: `init_steps(step_names: List[str])`, `update_step(name, status, duration, items, retries, metrics)`
- `MetricsCard`: `update_metrics(cpu_pct, memory_mb, db_size_mb, throughput, eta_sec)`
- `LogStreamWidget`: `write_log(message: str)`

- [ ] **Step 1: Write failing tests in `tests/test_monitoring/test_tui_widgets.py`**

```python
import pytest
from src.monitoring.tui.widgets import (
    HeaderWidget,
    StepListWidget,
    MetricsCard,
    LogStreamWidget,
)


def test_header_widget_init_and_update():
    header = HeaderWidget(title="VOCAB CRAFT TEST")
    assert "VOCAB CRAFT TEST" in header.title
    header.update_status(status="RUNNING", elapsed=65.0, workers=4)
    assert header.status == "RUNNING"
    assert header.elapsed_str == "00:01:05"


def test_step_list_widget_init_and_update():
    step_list = StepListWidget()
    step_list.init_steps(["ingest_kaikki", "translate_defs"])
    assert "ingest_kaikki" in step_list.steps_data
    assert step_list.steps_data["ingest_kaikki"]["status"] == "PENDING"

    step_list.update_step("ingest_kaikki", status="SUCCESS", duration=12.5, items=5000, retries=0, metrics="400 items/s")
    assert step_list.steps_data["ingest_kaikki"]["status"] == "SUCCESS"
    assert step_list.steps_data["ingest_kaikki"]["items"] == 5000


def test_metrics_card_update():
    card = MetricsCard()
    card.update_metrics(cpu_pct=35.5, memory_mb=512.0, db_size_mb=120.5, throughput=1500.0, eta_sec=90.0)
    assert card.cpu_pct == 35.5
    assert card.memory_mb == 512.0
    assert card.eta_str == "00:01:30"


def test_log_stream_widget_instantiation():
    log_stream = LogStreamWidget()
    assert log_stream is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_monitoring/test_tui_widgets.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/monitoring/tui/widgets.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_monitoring/test_tui_widgets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/monitoring/ tests/test_monitoring/
git commit -m "feat(monitoring): implement modular TUI widgets in src/monitoring/tui/widgets.py"
```

---

### Task 2: Implement `PipelineProgressApp` & `TUILoggingHandler` (`src/monitoring/tui/progress.py`)

**Files:**
- Create: `src/monitoring/tui/progress.py`
- Modify: `src/pipeline/monitor/dashboard.py`
- Create: `tests/test_monitoring/test_progress_app.py`

**Interfaces:**
- `PipelineProgressApp(App)`: Textual application composing header, step list, metrics card, and log stream.
- `TUILoggingHandler(logging.Handler)`: Redirects standard logs to TUI app.
- Backward-compatible `src/pipeline/monitor/dashboard.py` alias.

- [ ] **Step 1: Write failing tests in `tests/test_monitoring/test_progress_app.py`**

```python
import logging
import pytest
from src.monitoring.tui.progress import PipelineProgressApp, TUILoggingHandler
from src.pipeline.monitor.dashboard import TextualPipelineDashboard, DashboardLoggingHandler


def test_progress_app_init_and_steps():
    app = PipelineProgressApp(title="TEST MONITOR")
    app.set_steps(["step1", "step2"])
    assert "step1" in app.step_list.steps_data
    assert "step2" in app.step_list.steps_data


def test_tui_logging_handler():
    app = PipelineProgressApp()
    handler = TUILoggingHandler(app)
    logger = logging.getLogger("test_tui_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Test log record output")
    assert len(app.logs_buffer) > 0
    assert "Test log record output" in app.logs_buffer[-1]


def test_backward_compatibility_alias():
    # Verify TextualPipelineDashboard is an alias/compatible subclass of PipelineProgressApp
    dashboard = TextualPipelineDashboard(title="LEGACY MONITOR")
    assert isinstance(dashboard, PipelineProgressApp)
    handler = DashboardLoggingHandler(dashboard)
    assert isinstance(handler, TUILoggingHandler)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_monitoring/test_progress_app.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/monitoring/tui/progress.py` and update `dashboard.py`**

Create `src/monitoring/tui/progress.py`:
```python
"""
Pipeline Progress Terminal User Interface (TUI) Application using Textual.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding

from src.monitoring.tui.widgets import (
    HeaderWidget,
    StepListWidget,
    MetricsCard,
    LogStreamWidget,
)

logger = logging.getLogger(__name__)


class TUILoggingHandler(logging.Handler):
    """Custom logging handler redirecting records to the PipelineProgressApp log stream."""

    def __init__(self, app: "PipelineProgressApp"):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            time_str = time.strftime("%H:%M:%S", time.localtime(record.created))
            level = record.levelname
            step_idx = getattr(self.app, "current_step_idx", "?")

            if msg.startswith("=== START:"):
                step_name = msg.replace("=== START:", "").strip()
                formatted = f"[bold cyan]▶ STEP {step_idx}: {step_name.upper()}[/bold cyan]"
            elif msg.startswith("=== END:"):
                formatted = ""
            else:
                formatted = f"   [dim]{time_str}[/dim] [{level}] {msg}"

            if formatted:
                self.app.add_log(formatted)
        except Exception:
            self.handleError(record)


class PipelineProgressApp(App):
    """Interactive Terminal User Interface for Monitoring Pipeline Execution."""

    TITLE = "VOCAB CRAFT ENGINE - PIPELINE MONITOR"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("p", "toggle_pause", "Pause/Resume", show=True),
        Binding("r", "refresh_view", "Refresh", show=True),
    ]

    def __init__(
        self,
        enabled: bool = True,
        title: str = "VOCAB CRAFT ENGINE - PIPELINE MONITOR",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.enabled = enabled
        self.title_str = title
        self.title = self.title_str
        self.header_widget = HeaderWidget(title=self.title_str)
        self.step_list = StepListWidget()
        self.metrics_card = MetricsCard()
        self.log_stream = LogStreamWidget()
        self.original_handlers: List[logging.Handler] = []
        self.dashboard_handler: Optional[TUILoggingHandler] = None
        self._worker_func: Optional[Callable[[], None]] = None
        self.start_time = time.time()
        self.logs_buffer: List[str] = []
        self.current_step_idx: str | int = "?"
        self.is_paused = False

    def compose(self) -> ComposeResult:
        yield self.header_widget
        yield self.step_list
        yield self.metrics_card
        yield self.log_stream

    def set_steps(self, step_names: List[str]) -> None:
        self.step_list.init_steps(step_names)

    def set_worker(self, worker_func: Callable[[], None]) -> None:
        self._worker_func = worker_func

    def add_log(self, message: str) -> None:
        self.logs_buffer.append(message)
        try:
            self.call_from_thread(self._append_log_to_ui, message)
        except Exception:
            pass

    def _append_log_to_ui(self, message: str) -> None:
        try:
            self.log_stream.write_log(message)
        except Exception:
            pass

    def update_step_status(
        self,
        step_name: str,
        status: str,
        duration: float = 0.0,
        items: int = 0,
        retries: int = 0,
        metrics: str = "",
    ) -> None:
        try:
            self.call_from_thread(
                self.step_list.update_step,
                step_name,
                status,
                duration,
                items,
                retries,
                metrics,
            )
        except Exception:
            self.step_list.update_step(step_name, status, duration, items, retries, metrics)

    def on_mount(self) -> None:
        root_logger = logging.getLogger()
        self.dashboard_handler = TUILoggingHandler(self)
        self.dashboard_handler.setLevel(logging.INFO)
        root_logger.addHandler(self.dashboard_handler)

        self.set_interval(1.0, self._periodic_refresh)

        if self._worker_func:
            self.run_worker_in_background()

    def _periodic_refresh(self) -> None:
        elapsed = time.time() - self.start_time
        self.header_widget.update_status(
            status="PAUSED" if self.is_paused else "RUNNING",
            elapsed=elapsed,
            workers=4,
        )

    @work(thread=True)
    def run_worker_in_background(self) -> None:
        if self._worker_func:
            try:
                self._worker_func()
            except Exception as e:
                logger.error("Pipeline worker execution failed: %s", e)
            finally:
                self.call_from_thread(self._on_worker_finished)

    def _on_worker_finished(self) -> None:
        self.header_widget.update_status("COMPLETED", time.time() - self.start_time)

    def action_toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        logger.info("Pipeline %s", "PAUSED" if self.is_paused else "RESUMED")

    def action_refresh_view(self) -> None:
        self.refresh()
```

Update `src/pipeline/monitor/dashboard.py` to re-export:
```python
"""
Pipeline Dashboard re-exporting modular TUI progress app for backward compatibility.
"""

from src.monitoring.tui.progress import (
    PipelineProgressApp as TextualPipelineDashboard,
    TUILoggingHandler as DashboardLoggingHandler,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_monitoring/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/monitoring/tui/progress.py src/pipeline/monitor/dashboard.py tests/test_monitoring/
git commit -m "feat(monitoring): implement PipelineProgressApp with Textual reactive controller"
```

---

### Task 3: Integration with CLI & Full Orchestration Verification

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `main.py`
- Test: `tests/test_monitoring/`
- Test: `tests/test_pipeline/test_orchestrator.py`

**Interfaces:**
- `--tui` / `--no-tui` CLI flag orchestration

- [ ] **Step 1: Verify CLI and Orchestrator use `PipelineProgressApp` smoothly**

Run: `./.venv/bin/pytest tests/test_monitoring/ tests/test_pipeline/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 2: Commit**

```bash
git add src/pipeline/cli.py main.py
git commit -m "feat(cli): verify TUI monitoring flag integration"
```

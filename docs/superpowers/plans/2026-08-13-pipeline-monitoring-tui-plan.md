# Pipeline Monitoring, Retry Mechanism, Dual Logging & Rich Terminal UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive pipeline monitoring subsystem featuring a real-time Rich Terminal UI, configurable per-step auto-retry with backoff, state resumption via `--resume`, and dual output logging (text logs + JSON data quality benchmark report).

**Architecture:** Extend `PipelineOrchestrator` to wrap steps in a `RetryPolicy` execution loop, stream progress and console output to a `RichPipelineDashboard`, track step state for resumption in `StateManager`, and generate structured run reports via `RunLogger` and `DataQualityMetrics`.

**Tech Stack:** Python 3.11+, `rich` (v13.7.0+), `pytest`, `pytest-asyncio`, `pydantic`.

**Spec:** [`docs/superpowers/specs/2026-08-13-pipeline-monitoring-tui-design.md`](file:///Users/hoojinguyen/Projects/vocab-craft-engine/docs/superpowers/specs/2026-08-13-pipeline-monitoring-tui-design.md)

## Global Constraints
- Python floor: `>=3.11`
- Terminal UI library: `rich>=13.7.0`
- Configurable max retries: default `3`
- Default state file: `.pipeline_state.json`
- Default log directory: `logs/` (logs file: `logs/pipeline_<timestamp>.log`, run report: `logs/runs/run_<timestamp>.json`, link: `logs/latest_run.json`)

---

### Task 1: Add `rich` Dependency & Extend `StepResult` Model

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/pipeline/core/result.py`
- Test: `tests/test_result.py`

**Interfaces:**
- Consumes: Existing `StepResult` and `StepStatus` in `src/pipeline/core/result.py`
- Produces: `StepResult` fields: `retry_count: int = 0`, `error_traceback: Optional[str] = None`, `data_metrics: Dict[str, Any] = field(default_factory=dict)`

- [ ] **Step 1: Write failing test for `StepResult` extensions**

```python
# tests/test_result.py
from src.pipeline.core.result import StepResult, StepStatus

def test_step_result_extended_fields():
    res = StepResult(
        step_name="test_step",
        status=StepStatus.SUCCESS,
        execution_time_seconds=1.5,
        items_processed=100,
        retry_count=2,
        error_traceback="Traceback details...",
        data_metrics={"schema_compliance": 1.0}
    )
    assert res.retry_count == 2
    assert res.error_traceback == "Traceback details..."
    assert res.data_metrics == {"schema_compliance": 1.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_result.py -v`
Expected: FAIL with `unexpected keyword argument 'retry_count'` or `error_traceback`.

- [ ] **Step 3: Update `pyproject.toml` and `src/pipeline/core/result.py`**

In `pyproject.toml`, add `"rich>=13.7.0"` under `dependencies`:
```toml
dependencies = [
    "spacy>=3.7.0",
    "ijson>=3.2.0",
    "duckdb>=0.9.0",
    "edge-tts>=6.1.0",
    "polars>=0.20.0",
    "pydantic>=2.5.0",
    "g2p-en>=2.1.0",
    "deep-translator>=1.11.0",
    "PyYAML>=6.0",
    "rich>=13.7.0",
]
```

In `src/pipeline/core/result.py`, update `StepResult`:
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class StepStatus(Enum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


@dataclass
class StepResult:
    step_name: str
    status: StepStatus
    execution_time_seconds: float = 0.0
    items_processed: int = 0
    retry_count: int = 0
    message: str = ""
    error: Optional[Exception] = None
    error_traceback: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    data_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineSummary:
    total_time_seconds: float
    results: List[StepResult]
    has_failures: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_result.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/pipeline/core/result.py tests/test_result.py
git commit -m "feat: add rich dependency and extend StepResult with retry and traceback metrics"
```

---

### Task 2: Implement `RetryPolicy` Module

**Files:**
- Create: `src/pipeline/core/retry.py`
- Test: `tests/test_retry.py`

**Interfaces:**
- Consumes: `StepResult`, `StepStatus` from `src/pipeline/core/result.py`, `PipelineContext`
- Produces: `RetryPolicy(max_retries: int, backoff_factor: float).execute_with_retry(step, context, logger)`

- [ ] **Step 1: Write failing tests for `RetryPolicy`**

```python
# tests/test_retry.py
import pytest
from unittest.mock import MagicMock
from src.pipeline.core.retry import RetryPolicy
from src.pipeline.core.result import StepResult, StepStatus

class DummyStep:
    name = "dummy_step"
    description = "Dummy description"
    
    def __init__(self, fail_times=0):
        self.attempts = 0
        self.fail_times = fail_times

    def run(self, context):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError(f"Failure attempt {self.attempts}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=50)

def test_retry_policy_success_first_try():
    step = DummyStep(fail_times=0)
    policy = RetryPolicy(max_retries=3, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock())
    assert res.status == StepStatus.SUCCESS
    assert res.retry_count == 0

def test_retry_policy_recovers_after_retry():
    step = DummyStep(fail_times=2)
    policy = RetryPolicy(max_retries=3, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock())
    assert res.status == StepStatus.SUCCESS
    assert res.retry_count == 2

def test_retry_policy_exhaustion():
    step = DummyStep(fail_times=5)
    policy = RetryPolicy(max_retries=2, backoff_factor=0.01)
    res = policy.execute_with_retry(step, context=MagicMock())
    assert res.status == StepStatus.FAILED
    assert res.retry_count == 2
    assert "Failure attempt" in res.message
    assert res.error_traceback is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pipeline.core.retry'`

- [ ] **Step 3: Write implementation for `RetryPolicy`**

Create `src/pipeline/core/retry.py`:
```python
import time
import logging
import traceback
from typing import Optional, Callable
from src.pipeline.core.result import StepResult, StepStatus
from src.pipeline.core.context import PipelineContext

logger = logging.getLogger(__name__)


class RetryPolicy:
    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def execute_with_retry(
        self,
        step: any,
        context: PipelineContext,
        on_retry_callback: Optional[Callable[[int, int, Exception], None]] = None
    ) -> StepResult:
        attempt = 0
        last_exception: Optional[Exception] = None

        while attempt <= self.max_retries:
            step_start = time.time()
            try:
                if attempt > 0:
                    logger.warning(
                        "[%s] Retrying step (Attempt %d/%d)...",
                        step.name, attempt, self.max_retries
                    )
                
                res = step.run(context)
                res.retry_count = attempt
                if res.execution_time_seconds == 0.0:
                    res.execution_time_seconds = round(time.time() - step_start, 2)
                return res

            except Exception as e:
                last_exception = e
                duration = round(time.time() - step_start, 2)
                tb_str = traceback.format_exc()
                
                if attempt < self.max_retries:
                    if on_retry_callback:
                        on_retry_callback(attempt + 1, self.max_retries, e)
                    sleep_time = self.backoff_factor * (attempt + 1)
                    logger.warning(
                        "[%s] Attempt %d failed after %.2fs: %s. Sleeping %.1fs...",
                        step.name, attempt + 1, duration, e, sleep_time
                    )
                    time.sleep(sleep_time)
                    attempt += 1
                else:
                    logger.error(
                        "[%s] Step failed after %d retries (%.2fs): %s",
                        step.name, self.max_retries, duration, e
                    )
                    return StepResult(
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        execution_time_seconds=duration,
                        retry_count=attempt,
                        message=str(e),
                        error=e,
                        error_traceback=tb_str
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/retry.py tests/test_retry.py
git commit -m "feat: implement RetryPolicy with exponential backoff and attempt tracking"
```

---

### Task 3: Implement Dual `RunLogger` & Data Quality Metrics

**Files:**
- Create: `src/pipeline/monitor/__init__.py`
- Create: `src/pipeline/monitor/metrics.py`
- Create: `src/pipeline/monitor/run_logger.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `StepResult`, `PipelineSummary`
- Produces: `RunLogger` creating file logs in `logs/` and JSON structured run report at `logs/runs/run_<timestamp>.json` and updating `logs/latest_run.json`

- [ ] **Step 1: Write failing unit test for `RunLogger` and `DataQualityMetrics`**

```python
# tests/test_monitor.py
import json
from pathlib import Path
from src.pipeline.monitor.run_logger import RunLogger
from src.pipeline.core.result import StepResult, StepStatus, PipelineSummary

def test_run_logger_creates_json_artifact(tmp_path):
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir=log_dir, run_id="run_test_123")
    
    results = [
        StepResult(
            step_name="test_step",
            status=StepStatus.SUCCESS,
            execution_time_seconds=1.2,
            items_processed=50,
            retry_count=0,
            data_metrics={"valid_records": 50}
        )
    ]
    summary = PipelineSummary(total_time_seconds=1.2, results=results, has_failures=False)
    
    json_path = logger.save_run_summary(summary)
    assert json_path.exists()
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert data["run_id"] == "run_test_123"
    assert data["status"] == "SUCCESS"
    assert len(data["steps"]) == 1
    assert data["steps"][0]["step_name"] == "test_step"
    assert data["steps"][0]["data_metrics"]["valid_records"] == 50
    
    latest_link = log_dir / "latest_run.json"
    assert latest_link.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_monitor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/pipeline/monitor/metrics.py` and `src/pipeline/monitor/run_logger.py`**

Create `src/pipeline/monitor/__init__.py` (empty).

Create `src/pipeline/monitor/metrics.py`:
```python
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class DataQualityMetrics:
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    additional_stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def schema_compliance_ratio(self) -> float:
        if self.total_records == 0:
            return 1.0
        return round(self.valid_records / self.total_records, 4)

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "schema_compliance_ratio": self.schema_compliance_ratio,
        }
        res.update(self.additional_stats)
        return res
```

Create `src/pipeline/monitor/run_logger.py`:
```python
import json
import logging
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from src.pipeline.core.result import PipelineSummary, StepResult

logger = logging.getLogger(__name__)


class RunLogger:
    def __init__(self, log_dir: Path = Path("logs"), run_id: Optional[str] = None):
        self.log_dir = log_dir
        self.runs_dir = self.log_dir / "runs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        
        self.now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id or f"run_{self.now_str}"
        self.log_file_path = self.log_dir / f"pipeline_{self.now_str}.log"
        self._setup_file_logging()

    def _setup_file_logging(self) -> None:
        file_handler = logging.FileHandler(self.log_file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

    def save_run_summary(self, summary: PipelineSummary, is_resumed: bool = False) -> Path:
        json_file_path = self.runs_dir / f"{self.run_id}.json"
        
        total_items = sum(r.items_processed for r in summary.results)
        throughput = round(total_items / summary.total_time_seconds, 2) if summary.total_time_seconds > 0 else 0.0
        
        run_data = {
            "run_id": self.run_id,
            "started_at": self.now_str,
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_runtime_seconds": summary.total_time_seconds,
            "status": "FAILED" if summary.has_failures else "SUCCESS",
            "is_resumed_run": is_resumed,
            "system_info": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform()
            },
            "summary_metrics": {
                "total_steps": len(summary.results),
                "successful_steps": sum(1 for r in summary.results if r.status.value == "SUCCESS"),
                "failed_steps": sum(1 for r in summary.results if r.status.value == "FAILED"),
                "skipped_steps": sum(1 for r in summary.results if r.status.value == "SKIPPED"),
                "total_items_processed": total_items,
                "overall_throughput_items_per_sec": throughput
            },
            "steps": [
                {
                    "step_name": r.step_name,
                    "status": r.status.value,
                    "execution_time_seconds": r.execution_time_seconds,
                    "items_processed": r.items_processed,
                    "retry_count": r.retry_count,
                    "message": r.message,
                    "data_metrics": r.data_metrics,
                    "error_details": {
                        "error_message": str(r.error) if r.error else None,
                        "stacktrace": r.error_traceback
                    } if r.error_traceback or r.error else None
                }
                for r in summary.results
            ]
        }
        
        json_file_path.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        latest_path = self.log_dir / "latest_run.json"
        latest_path.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        logger.info("Saved structured run report to %s", json_file_path)
        return json_file_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/monitor/ tests/test_monitor.py
git commit -m "feat: add RunLogger and DataQualityMetrics for JSON artifact generation"
```

---

### Task 4: Implement `RichPipelineDashboard`

**Files:**
- Create: `src/pipeline/monitor/dashboard.py`
- Modify: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `rich.live.Live`, `rich.table.Table`, `rich.layout.Layout`, `rich.panel.Panel`, `rich.progress.Progress`, `StepResult`
- Produces: `RichPipelineDashboard` with methods: `start()`, `update_step(name, status, duration, items, retries, metrics)`, `add_log(message)`, `stop()`

- [ ] **Step 1: Add TUI Fallback test in `tests/test_monitor.py`**

```python
# Add to tests/test_monitor.py
from src.pipeline.monitor.dashboard import RichPipelineDashboard

def test_dashboard_initialization_no_tui():
    dash = RichPipelineDashboard(enabled=False)
    dash.start()
    dash.update_step("test_step", "RUNNING")
    dash.stop()
    assert not dash.is_active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_monitor.py::test_dashboard_initialization_no_tui -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pipeline.monitor.dashboard'`

- [ ] **Step 3: Implement `RichPipelineDashboard`**

Create `src/pipeline/monitor/dashboard.py`:
```python
import sys
import time
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.style import Style


class RichPipelineDashboard:
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
        for name in step_names:
            self.steps_data[name] = {
                "status": "PENDING",
                "duration": 0.0,
                "items": 0,
                "retries": 0,
                "metrics": ""
            }

    def start(self) -> None:
        if not self.enabled:
            return
        self.is_active = True
        self.start_time = time.time()
        self.live = Live(self._generate_layout(), console=self.console, refresh_per_second=8, auto_refresh=True)
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
        self.logs_buffer.append(log_line)
        if len(self.logs_buffer) > 10:
            self.logs_buffer.pop(0)
        if self.live and self.is_active:
            self.live.update(self._generate_layout())

    def _generate_layout(self) -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body", ratio=2),
            Layout(name="footer", size=8)
        )

        elapsed = round(time.time() - self.start_time, 1)
        completed = sum(1 for s in self.steps_data.values() if s["status"] in ("SUCCESS", "SKIPPED"))
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
        if self.live and self.is_active:
            self.live.stop()
        self.is_active = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/monitor/dashboard.py tests/test_monitor.py
git commit -m "feat: implement RichPipelineDashboard for real-time TUI execution monitoring"
```

---

### Task 5: Integrate Retry, Resume & TUI Dashboard into `PipelineOrchestrator`

**Files:**
- Modify: `src/pipeline/core/orchestrator.py`
- Modify: `src/pipeline/core/state_manager.py`
- Test: `tests/test_orchestrator_monitoring.py`

**Interfaces:**
- Consumes: `RetryPolicy`, `RichPipelineDashboard`, `RunLogger`, `StateManager`
- Produces: `PipelineOrchestrator.run(context)` supporting `--resume`, auto-retry, and real-time dashboard visualization.

- [ ] **Step 1: Write integration test for `PipelineOrchestrator` with `--resume` and retries**

Create `tests/test_orchestrator_monitoring.py`:
```python
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import StepResult, StepStatus
from src.pipeline.core.context import PipelineContext

class StepA:
    name = "step_a"
    description = "Step A"
    def should_skip(self, ctx): return False, ""
    def run(self, ctx): return StepResult("step_a", StepStatus.SUCCESS, items_processed=10)

class StepB:
    name = "step_b"
    description = "Step B"
    def should_skip(self, ctx): return False, ""
    def run(self, ctx): return StepResult("step_b", StepStatus.SUCCESS, items_processed=20)

def test_orchestrator_resume_skips_completed_steps(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    registry = StepRegistry()
    registry.register(StepA())
    registry.register(StepB())

    # Pre-populate state with step_a SUCCESS
    orchestrator = PipelineOrchestrator(registry=registry, state_file=state_file)
    orchestrator.state_manager.save_step_status("step_a", "SUCCESS", 1.0, 10)

    ctx = MagicMock()
    ctx.args = MagicMock()
    ctx.args.dry_run = False
    ctx.args.resume = True
    ctx.args.steps = None
    ctx.args.skip_steps = None
    ctx.args.max_retries = 2
    ctx.args.tui = False

    summary = orchestrator.run(ctx)
    
    assert summary.results[0].step_name == "step_a"
    assert summary.results[0].status == StepStatus.SKIPPED
    assert summary.results[1].step_name == "step_b"
    assert summary.results[1].status == StepStatus.SUCCESS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator_monitoring.py -v`
Expected: FAIL (because `--resume` logic and parameters are not yet in `orchestrator.py`).

- [ ] **Step 3: Update `src/pipeline/core/orchestrator.py`**

Update `src/pipeline/core/orchestrator.py`:
```python
import time
import logging
from pathlib import Path
from typing import List, Optional

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus, StepResult, PipelineSummary
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.state_manager import StateManager
from src.pipeline.core.retry import RetryPolicy
from src.pipeline.monitor.dashboard import RichPipelineDashboard
from src.pipeline.monitor.run_logger import RunLogger

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self, registry: StepRegistry, state_file: Path = Path(".pipeline_state.json")):
        self.registry = registry
        self.state_manager = StateManager(state_file=state_file)

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.time()
        results: List[StepResult] = []

        dry_run = getattr(context.args, "dry_run", False)
        resume = getattr(context.args, "resume", False)
        tui_enabled = getattr(context.args, "tui", True)
        max_retries = getattr(context.args, "max_retries", 3)
        log_dir = Path(getattr(context.args, "log_dir", "logs"))

        run_logger = RunLogger(log_dir=log_dir)
        dashboard = RichPipelineDashboard(enabled=tui_enabled and not dry_run)

        if not dry_run and not resume:
            self.state_manager.clear_state()

        previous_state = self.state_manager.load_state() if resume else {}

        include_steps = getattr(context.args, "steps", None)
        if isinstance(include_steps, str):
            include_steps = [s.strip() for s in include_steps.split(",") if s.strip()]

        skip_steps = getattr(context.args, "skip_steps", None)
        if isinstance(skip_steps, str):
            skip_steps = [s.strip() for s in skip_steps.split(",") if s.strip()]

        steps_to_run = self.registry.filter_steps(include_steps=include_steps, skip_steps=skip_steps)
        dashboard.set_steps([s.name for s in steps_to_run])

        logger.info("==========================================================")
        logger.info("   STARTING VOCAB CRAFT ENGINE PIPELINE EXECUTION        ")
        logger.info("==========================================================")

        dashboard.start()
        has_failures = False

        retry_policy = RetryPolicy(max_retries=max_retries)

        try:
            for step in steps_to_run:
                step_start = time.time()
                dashboard.update_step(step.name, "RUNNING")

                # Resume check
                if resume and previous_state.get(step.name, {}).get("status") == "SUCCESS":
                    msg = f"Skipped via --resume (already completed in previous run)"
                    logger.info("[%s] %s", step.name, msg)
                    prev = previous_state[step.name]
                    res = StepResult(
                        step_name=step.name,
                        status=StepStatus.SKIPPED,
                        execution_time_seconds=prev.get("duration", 0.0),
                        items_processed=prev.get("items", 0),
                        message=msg
                    )
                    results.append(res)
                    dashboard.update_step(step.name, "SKIPPED", res.execution_time_seconds, res.items_processed, 0, "Resumed")
                    continue

                try:
                    skip, reason = step.should_skip(context)

                    if dry_run:
                        msg = f"[DRY-RUN] Would run '{step.name}'. Skip: {skip} ({reason})"
                        logger.info(msg)
                        res = StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED,
                            execution_time_seconds=0.0,
                            message=msg
                        )
                        results.append(res)
                        dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, "Dry-Run")
                        continue

                    if skip:
                        logger.info("[%s] SKIPPED: %s", step.name, reason)
                        res = StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED,
                            execution_time_seconds=0.0,
                            message=reason
                        )
                        results.append(res)
                        dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, reason)
                        continue

                    def on_retry(attempt, total, exc):
                        dashboard.update_step(step.name, f"RETRY {attempt}/{total}", retries=attempt)
                        dashboard.add_log(f"[WARNING] [{step.name}] Attempt {attempt}/{total} failed: {exc}")

                    res = retry_policy.execute_with_retry(step, context, on_retry_callback=on_retry)
                    duration = round(time.time() - step_start, 2)
                    res.execution_time_seconds = duration
                    results.append(res)

                    if res.status == StepStatus.SUCCESS:
                        self.state_manager.save_step_status(step.name, "SUCCESS", duration, res.items_processed)
                        dashboard.update_step(
                            step.name, "SUCCESS", duration, res.items_processed, res.retry_count,
                            f"valid: {res.items_processed}"
                        )
                    else:
                        has_failures = True
                        self.state_manager.save_step_status(step.name, "FAILED", duration, 0)
                        dashboard.update_step(step.name, "FAILED", duration, 0, res.retry_count, res.message[:20])
                        try:
                            step.rollback(context)
                        except Exception as rb_err:
                            logger.warning("[%s] Rollback warning: %s", step.name, rb_err)
                        break

                except Exception as e:
                    duration = round(time.time() - step_start, 2)
                    has_failures = True
                    res = StepResult(
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        execution_time_seconds=duration,
                        message=str(e)
                    )
                    results.append(res)
                    dashboard.update_step(step.name, "FAILED", duration, 0, 0, str(e)[:20])
                    break
        finally:
            dashboard.stop()

        total_time = round(time.time() - start_time, 2)
        summary = PipelineSummary(total_time_seconds=total_time, results=results, has_failures=has_failures)
        
        run_logger.save_run_summary(summary, is_resumed=resume)
        self._print_summary(results, total_time)
        
        return summary

    def _print_summary(self, results: List[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 65)
        logger.info(f"{'STEP NAME':<25} | {'STATUS':<8} | {'TIME (s)':<8} | {'ITEMS':<8}")
        logger.info("-" * 65)
        for r in results:
            logger.info(f"{r.step_name:<25} | {r.status.value:<8} | {r.execution_time_seconds:<8.2f} | {r.items_processed:<8}")
        logger.info("=" * 65)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 65 + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator_monitoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/orchestrator.py tests/test_orchestrator_monitoring.py
git commit -m "feat: integrate RetryPolicy, RichPipelineDashboard, and --resume in PipelineOrchestrator"
```

---

### Task 6: Add CLI Arguments and Update Entrypoint

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `main.py`
- Test: Existing tests and end-to-end verification

**Interfaces:**
- Consumes: CLI parser options
- Produces: `--resume`, `--no-tui`, `--max-retries`, `--log-dir` flags passed to `PipelineContext` and `PipelineOrchestrator`

- [ ] **Step 1: Update `src/pipeline/cli.py` to support new monitoring flags**

```python
# In src/pipeline/cli.py, add argument definitions inside parse_arguments()
parser.add_argument("--resume", action="store_true", help="Resume execution from previous failed state")
parser.add_argument("--no-tui", action="store_false", dest="tui", default=True, help="Disable Rich Terminal UI dashboard")
parser.add_argument("--max-retries", type=int, default=3, help="Maximum auto-retries per step (default: 3)")
parser.add_argument("--log-dir", type=str, default="logs", help="Directory to store file logs and JSON reports")
```

- [ ] **Step 2: Run pytest to verify all existing tests pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/pipeline/cli.py main.py
git commit -m "feat: add CLI options for --resume, --no-tui, --max-retries, and --log-dir"
```

---

### Task 7: End-to-End Verification & Verification Run

**Files:**
- Execute: `pytest` and `python main.py --dry-run`

- [ ] **Step 1: Run complete test suite**

Run: `pytest`
Expected: All tests pass cleanly.

- [ ] **Step 2: Run pipeline dry-run with TUI**

Run: `python main.py --dry-run`
Expected: Real-time dashboard renders dry-run steps and saves report to `logs/latest_run.json`.

- [ ] **Step 3: Final Commit**

```bash
git commit --allow-empty -m "chore: completed pipeline monitoring and TUI implementation"
```

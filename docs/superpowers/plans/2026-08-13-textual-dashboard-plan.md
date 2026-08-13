# Textual TUI Dashboard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the pipeline monitoring dashboard from `rich` to `textual` to support advanced TUI features like scrolling and interactivity.

**Architecture:** We use a Background Worker Thread approach. The main thread runs the `textual` app (`TextualPipelineDashboard`), while the pipeline execution loop is dispatched into a background thread using Textual's `@work(thread=True)` decorator. UI updates and logging from the background thread are safely routed back to the main thread using `app.call_from_thread()`.

**Tech Stack:** `textual`, `rich`, `pytest-asyncio`

**Spec:** `docs/superpowers/specs/2026-08-13-textual-dashboard-design.md`

## Global Constraints
- Python >=3.11
- Must maintain all existing logging output and pipeline functionality.
- Code changes must be covered by unit tests.

---

### Task 1: Add Textual Dependency

**Files:**
- Modify: `pyproject.toml:23-26`

**Interfaces:**
- Consumes: None
- Produces: `textual` package availability.

- [ ] **Step 1: Add textual to pyproject.toml**

```toml
    "PyYAML>=6.0",
    "rich>=13.7.0",
    "textual>=0.70.0",
]
```

- [ ] **Step 2: Run make install to update dependencies**

```bash
make install
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: Add textual dependency"
```

---

### Task 2: Implement Textual Dashboard

**Files:**
- Modify: `src/pipeline/monitor/dashboard.py`

**Interfaces:**
- Consumes: `DashboardLoggingHandler`
- Produces: `TextualPipelineDashboard` inheriting from `textual.app.App`. Methods `update_step`, `add_log`, `set_worker`.

- [ ] **Step 1: Write Textual UI Implementation**

Replace `RichPipelineDashboard` with `TextualPipelineDashboard` in `src/pipeline/monitor/dashboard.py`.
It should use `textual.app.App`, `textual.widgets.Header`, `textual.widgets.DataTable`, and `textual.widgets.RichLog`.
It must define a `compose` method to layout these widgets.
It must define `set_worker(self, worker_func)` to receive the pipeline execution loop.
It must define an `on_mount` method that uses `@work(thread=True)` to execute the `worker_func`.
`add_log` and `update_step` must use `self.call_from_thread` to update the `RichLog` and `DataTable` respectively.
`DashboardLoggingHandler` must be updated to ensure `emit` safely uses `dashboard.add_log`.

- [ ] **Step 2: Run linter/type checker to verify syntax**

```bash
ruff check src/pipeline/monitor/dashboard.py
```

- [ ] **Step 3: Commit**

```bash
git add src/pipeline/monitor/dashboard.py
git commit -m "feat: Implement TextualPipelineDashboard"
```

---

### Task 3: Refactor Pipeline Orchestrator

**Files:**
- Modify: `src/pipeline/core/orchestrator.py`

**Interfaces:**
- Consumes: `TextualPipelineDashboard`
- Produces: Updated `run` logic that spins up the Textual app and delegates execution.

- [ ] **Step 1: Extract execution loop to a method**

In `src/pipeline/core/orchestrator.py`, rename the `try...finally` loop inside `run()` into a new method `_execute_pipeline(self, steps_to_run, context, run_logger, resume, previous_state, dashboard, results, start_time)`.

- [ ] **Step 2: Start Textual App in run()**

In `run()`, instantiate `TextualPipelineDashboard`.
If TUI is enabled:
`dashboard.set_worker(lambda: self._execute_pipeline(...))`
`dashboard.run()` (This blocks until the pipeline finishes and user closes, or app exits).
If TUI is disabled:
`self._execute_pipeline(...)` directly in the main thread.

- [ ] **Step 3: Run pipeline with dry-run to verify integration**

```bash
python main.py --dry-run
```
Expected: The textual TUI launches, shows dry-run steps, and logs appear.

- [ ] **Step 4: Commit**

```bash
git add src/pipeline/core/orchestrator.py
git commit -m "refactor: Integrate Textual app loop into orchestrator"
```

---

### Task 4: Update Tests

**Files:**
- Modify: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `TextualPipelineDashboard`

- [ ] **Step 1: Update test_dashboard_logging_redirection**

In `tests/test_monitor.py`, since Textual requires an async loop to test, rewrite `test_dashboard_logging_redirection` to be `async def` and use `async with dashboard.run_test() as pilot:` to verify that logs are properly captured and the `RichLog` widget receives the text. You must use `pytest.mark.asyncio`.

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_monitor.py -v
pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_monitor.py
git commit -m "test: Update monitor tests for Textual async app"
```

# Terminal UI (TUI) Monitoring Module Design (Phase 3)

## 1. Executive Summary

This specification defines the implementation of the modular Terminal User Interface (TUI) monitoring subsystem for the Pipeline V2 engine using Textual and Rich:
1. **Component Widgets (`src/monitoring/tui/widgets.py`)**:
   - `HeaderWidget`: Pipeline engine title, global lifecycle status, total elapsed time, active worker count.
   - `StepListWidget`: Visual step status table with emoji badges (PENDING ⏸, RUNNING ⏳, SUCCESS ✅, FAILED ❌, SKIPPED ⏭), execution duration, items processed, retry counts.
   - `MetricsCard`: Real-time system telemetry (CPU %, Memory RSS, DuckDB file size, throughput items/s, estimated ETA).
   - `LogStreamWidget`: Live auto-scrolling log terminal with Rich syntax markup.
2. **Application Controller (`src/monitoring/tui/progress.py`)**:
   - `PipelineProgressApp(App)`: Main Textual application composing the UI layout with reactive updates.
   - `TUILoggingHandler(logging.Handler)`: Intercepts standard library logging and pushes formatted records to the log stream.
   - Keybindings for interactive control (`q` quit, `p` pause/resume, `r` refresh, `d` toggle detail view).
3. **Integration & Compatibility**:
   - Backward-compatible aliasing in `src/pipeline/monitor/dashboard.py`.
   - Comprehensive test suite in `tests/test_monitoring/`.

---

## 2. Architecture & UI Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ HeaderWidget                                                                │
│ [VOCAB CRAFT ENGINE] | Status: RUNNING | Elapsed: 00:04:12 | Workers: 4      │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ StepListWidget                       │ MetricsCard                          │
│  #  Step Name        Status   Time   │  • CPU Usage: 42.1%                  │
│  ─────────────────────────────────── │  • Memory RSS: 1.2 GB                │
│  1  ingest_kaikki    ✅ SUCCESS 12s  │  • Staging DB: 185 MB                │
│  2  ingest_wordnet   ✅ SUCCESS  4s  │  • Speed: 2,450 words/sec            │
│  3  translate_defs   ▶ RUNNING  45s  │  • Total Processed: 154,200          │
│  4  tag_pos          ⏸ PENDING   --  │  • Est. Remaining: ~00:06:30         │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ LogStreamWidget (RichLog auto-scroll)                                       │
│ [14:35:10] [INFO] Ingested 50,000 definitions from Kaikki...                │
│ [14:35:22] [INFO] ArgosTranslate worker pool active (4 threads)...          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 `src/monitoring/tui/widgets.py`

#### `HeaderWidget`
- Properties: `pipeline_title`, `status`, `elapsed_seconds`, `worker_count`.
- Renders header bar with styled title and status pill.

#### `StepListWidget`
- Uses Textual `DataTable` with columns: `#`, `Step Name`, `Status`, `Duration`, `Items`, `Retries`, `Metrics`.
- Methods:
  - `init_steps(step_names: List[str]) -> None`
  - `update_step(step_name: str, status: str, duration: float, items: int, retries: int, metrics: str) -> None`

#### `MetricsCard`
- Uses Textual `Static` container.
- Displays CPU percentage, memory RSS, staging database file size, processed throughput, and ETA.
- Method: `update_metrics(cpu_pct: float, memory_mb: float, db_size_mb: float, throughput: float, eta_sec: float) -> None`

#### `LogStreamWidget`
- Extends Textual `RichLog(highlight=True, markup=True)`.
- Method: `write_log(message: str) -> None`

### 3.2 `src/monitoring/tui/progress.py`

#### `TUILoggingHandler(logging.Handler)`
- Captures log records, formats timestamps, step markers (`=== START: ...`, `=== END: ...`), and forwards to `PipelineProgressApp.add_log()`.

#### `PipelineProgressApp(App)`
- Composes `HeaderWidget`, `StepListWidget`, `MetricsCard`, `LogStreamWidget`.
- Background worker execution (`set_worker(fn)`).
- Keybindings:
  - `q`: Quit app.
  - `p`: Pause/Resume.
  - `r`: Force refresh.
  - `d`: Toggle log detail.
- Backward compatibility: Re-exported via `src/pipeline/monitor/dashboard.py` as `TextualPipelineDashboard`.

---

## 4. Verification & Testing Plan

1. **`tests/test_monitoring/test_tui_widgets.py`**:
   - Test widget creation and initial state for `HeaderWidget`, `StepListWidget`, `MetricsCard`, and `LogStreamWidget`.
   - Test `update_step` and `update_metrics` updates.
2. **`tests/test_monitoring/test_progress_app.py`**:
   - Test `PipelineProgressApp` composition and step data initialization.
   - Test `TUILoggingHandler` record formatting and log message routing.
   - Test backward compatibility import from `src.pipeline.monitor.dashboard`.

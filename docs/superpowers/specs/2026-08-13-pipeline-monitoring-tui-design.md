# Design Specification: Pipeline Monitoring, Retry Mechanism, Dual Logging & Rich Terminal UI

- **Date:** 2026-08-13
- **Status:** Approved
- **Target Project:** `vocab-craft-engine`
- **Subsystem:** Pipeline Orchestration & Monitoring Framework

---

## 1. Executive Summary & Goals

The `vocab-craft-engine` requires an enterprise-grade monitoring, metrics, retry, and logging framework to provide clear visibility into pipeline execution, track data accuracy, handle transient errors, and record performance benchmarks for continuous engine improvement.

### Core Objectives:
1. **Real-time Terminal UI (TUI):** A rich, interactive, non-flickering visual dashboard using the `rich` library showing step status, durations, processed items, retry counts, progress bars, and a live console log stream.
2. **Step Retry Policy:** Automatic per-step retries with configurable max attempts and exponential backoff to recover from transient failures (e.g., API timeouts in TTS/translation).
3. **Pipeline Resumption (`--resume`):** Ability to skip previously successful steps stored in `.pipeline_state.json` and resume execution directly from the failed step.
4. **Dual Logging System:**
   - Detailed plain-text file log (`logs/pipeline_<timestamp>.log`).
   - Machine-readable JSON execution & data quality report (`logs/runs/run_<timestamp>.json` and symlinked `logs/latest_run.json`).
5. **Data Quality & Performance Metrics:** Measurement of throughput (items/sec), schema compliance ratios, token counts, and accuracy scores per step.

---

## 2. System Architecture & Module Structure

```
src/pipeline/
├── core/
│   ├── orchestrator.py        # Pipeline execution loop integrated with Retry, Monitor & Resume
│   ├── result.py              # Extended StepResult with retry_count, error_traceback, metrics
│   ├── retry.py               # RetryPolicy implementation (max_retries, backoff)
│   ├── state_manager.py       # Manages .pipeline_state.json for --resume
│   └── context.py             # PipelineContext with metric gathering helpers
├── monitor/                   # Monitoring Subsystem
│   ├── __init__.py
│   ├── dashboard.py           # RichPipelineDashboard (Live TUI, Progress bars, Log panel)
│   ├── run_logger.py          # Dual Logger (File log + JSON Run History)
│   └── metrics.py             # DataQualityMetrics collector & score calculator
└── cli.py                     # CLI parser supporting --resume, --tui/--no-tui, --max-retries
```

---

## 3. Detailed Component Specifications

### 3.1 `RetryPolicy` (`src/pipeline/core/retry.py`)
Encapsulates step execution retry logic:
- `max_retries`: Maximum attempt count per step (default: `3`).
- `backoff_factor`: Delay multiplier between attempts (default: `1.5s`).
- `run_with_retry(step, context)`: Wraps `step.run(context)` in a loop. Captures transient exceptions, updates `StepResult.retry_count`, and re-raises/records final failure if max retries exceeded.

### 3.2 `RichPipelineDashboard` (`src/pipeline/monitor/dashboard.py`)
Builds a 3-part layout using `rich.live.Live`, `rich.table.Table`, `rich.progress.Progress`, and `rich.panel.Panel`:
- **Header Box:** Displays Run ID, Elapsed Time, Overall Progress Percentage, and Active Step Count.
- **Status Table:** Columns for `#`, `Step Name`, `Status` (color-coded badges: `SUCCESS`, `RUNNING`, `RETRY 1/3`, `FAILED`, `SKIPPED`), `Time (s)`, `Items`, `Retries`, `Data Metrics`.
- **Live Console Stream:** Bottom panel rendering real-time log messages via `RichHandler`.
- **Fallback:** Automatically falls back to standard text logging when `stdout` is not a TTY or `--no-tui` is specified.

### 3.3 `RunLogger` (`src/pipeline/monitor/run_logger.py`)
- Manages output directory `logs/` and `logs/runs/`.
- Initializes standard file logging: `logs/pipeline_<timestamp>.log`.
- Generates JSON benchmark report: `logs/runs/run_<timestamp>.json` containing system environment info, overall runtime metrics, and per-step breakdown.
- Updates `logs/latest_run.json` pointer for quick inspection.

### 3.4 Data Metrics Schema (`logs/runs/run_<timestamp>.json`)
```json
{
  "run_id": "run_20260813_152200",
  "started_at": "2026-08-13T15:22:00Z",
  "completed_at": "2026-08-13T15:23:24Z",
  "total_runtime_seconds": 84.52,
  "status": "SUCCESS",
  "is_resumed_run": false,
  "system_info": {
    "python_version": "3.11.8",
    "platform": "macOS-14.5"
  },
  "summary_metrics": {
    "total_steps": 6,
    "successful_steps": 6,
    "failed_steps": 0,
    "skipped_steps": 0,
    "total_items_processed": 15420,
    "overall_throughput_items_per_sec": 182.44
  },
  "steps": [
    {
      "step_name": "raw_ingestion",
      "description": "Ingest raw CEFR & Dictionary JSON files into DuckDB Staging",
      "status": "SUCCESS",
      "execution_time_seconds": 2.41,
      "items_processed": 15420,
      "retry_count": 0,
      "data_metrics": {
        "source_files_count": 4,
        "valid_records": 15420,
        "invalid_records": 0,
        "schema_compliance_ratio": 1.0
      },
      "error_details": null
    }
  ]
}
```

### 3.5 Resume Pipeline Logic (`--resume`)
- Reads `.pipeline_state.json`.
- Step status `SUCCESS` in state -> step is marked `SKIPPED (Resumed)` instantly.
- Pipeline execution resumes from the first `FAILED` or `PENDING` step.

---

## 4. Dependencies

Add `rich` to `pyproject.toml`:
```toml
dependencies = [
    "rich>=13.7.0",
    ...
]
```

---

## 5. Verification & Testing Strategy

1. **Unit Tests (`tests/test_retry.py`):**
   - Test step retry success after 1 failed attempt.
   - Test step retry exhaustion reaching `max_retries` and returning `StepStatus.FAILED`.
2. **Resume Unit Tests (`tests/test_state_manager.py`):**
   - Test state persistence and partial pipeline resumption skipping completed steps.
3. **Logger & TUI Unit Tests (`tests/test_monitor.py`):**
   - Test `RunLogger` JSON file creation and accuracy of metrics payload.
   - Test TUI non-TTY fallback behavior.
4. **Integration Test (`main.py` execution):**
   - Execute full pipeline run with `--tui` and `--resume` flags to verify real-time dashboard and output files.

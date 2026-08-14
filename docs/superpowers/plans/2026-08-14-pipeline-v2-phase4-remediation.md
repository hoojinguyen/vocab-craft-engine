# Pipeline V2 Phase 4 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 4 by implementing multi-threaded DAG level concurrency in `PipelineOrchestrator`, honoring optional step toggles, creating `config/pipeline_config.yaml`, fixing CLI status/reset schema mismatches, deleting legacy `01_..` duplicate step files, and achieving 100% test pass rate across the entire repository.

**Architecture:**
- `PipelineOrchestrator` executes independent steps within each DAG topological level concurrently using `ThreadPoolExecutor` while respecting DuckDB multi-connection concurrency.
- `PipelineContext` and `StateManager` evaluate `optional = True` steps against `--enable` flags and YAML configuration.
- `config/pipeline_config.yaml` provides centralized configuration for workers, batch sizes, memory limits, and step toggles.
- Obsolete duplicate numbered files (`src/pipeline/steps/01_...` to `15_...`) deleted.
- Legacy test files updated to match V2 architecture.

**Tech Stack:** Python 3.11+, DuckDB, Concurrent Futures, PyYAML, orjson, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-pipeline-v2-remediation-spec.md`

## Global Constraints
- Concurrency within DAG levels must run without deadlocks or DuckDB connection conflicts.
- `optional = True` steps must not run unless explicitly enabled via CLI or config.
- Legacy `01_`–`15_` duplicate files must be removed, keeping only V2 step files in `src/pipeline/steps/`.
- 100% test pass rate across the whole repo (`pytest tests/`).

---

### Task 1: Pipeline Orchestrator Concurrency & Optional Step Toggles

**Files:**
- Modify: `src/pipeline/core/orchestrator.py`
- Modify: `src/pipeline/core/context.py`
- Test: `tests/test_pipeline/test_orchestrator_concurrency.py`

**Interfaces:**
- Consumes: DAG topological levels and PipelineContext with enabled optional step list.
- Produces: Parallel step execution within levels and correct skip behavior for disabled optional steps.

- [ ] **Step 1: Write test for Level Concurrency and Optional Step Skipping**

```python
# tests/test_pipeline/test_orchestrator_concurrency.py
import time
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.dag import PipelineDAG
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import StepResult, StepStatus

class SleepStepA(BaseStep):
    name = "sleep_a"
    execution_type = "cpu"
    def run(self, ctx):
        time.sleep(0.3)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=10)

class SleepStepB(BaseStep):
    name = "sleep_b"
    execution_type = "cpu"
    def run(self, ctx):
        time.sleep(0.3)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=20)

class OptionalStepC(BaseStep):
    name = "opt_c"
    optional = True
    def run(self, ctx):
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=5)

def test_orchestrator_runs_level_steps_concurrently(tmp_path):
    mgr = DuckDBManager(tmp_path / "test.duckdb")
    mgr.init_schema()
    registry = StepRegistry()
    registry.register(SleepStepA)
    registry.register(SleepStepB)
    dag = PipelineDAG(registry)

    orchestrator = PipelineOrchestrator(dag, max_workers=2)
    ctx = PipelineContext(db=mgr, output_dir=tmp_path)
    
    t0 = time.perf_counter()
    summary = orchestrator.run(ctx)
    elapsed = time.perf_counter() - t0

    assert summary.success is True
    # Two 0.3s steps running in parallel should take significantly less than 0.6s
    assert elapsed < 0.55
    mgr.close()

def test_orchestrator_skips_disabled_optional_step(tmp_path):
    mgr = DuckDBManager(tmp_path / "test_opt.duckdb")
    mgr.init_schema()
    registry = StepRegistry()
    registry.register(OptionalStepC)
    dag = PipelineDAG(registry)

    orchestrator = PipelineOrchestrator(dag)
    ctx = PipelineContext(db=mgr, output_dir=tmp_path, enabled_optional_steps=[])
    summary = orchestrator.run(ctx)

    assert summary.success is True
    assert summary.step_results["opt_c"].status == StepStatus.SKIPPED
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_pipeline/test_orchestrator_concurrency.py -v`

- [ ] **Step 3: Implement Concurrency & Optional Skipping in `PipelineOrchestrator`**

Modify `src/pipeline/core/orchestrator.py`:
- Use `concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)` to execute steps inside each DAG level concurrently.
- Check `step.optional and step.name not in ctx.enabled_optional_steps` to immediately return `StepStatus.SKIPPED`.
- Collect all step results and propagate state to StateManager and DuckDB metadata.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_pipeline/test_orchestrator_concurrency.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/pipeline/core/orchestrator.py src/pipeline/core/context.py tests/test_pipeline/test_orchestrator_concurrency.py
git commit -m "feat(orchestrator): implement concurrent DAG level execution and optional step toggling"
```

---

### Task 2: Pipeline Configuration YAML & Settings Integration

**Files:**
- Create: `config/pipeline_config.yaml`
- Modify: `config/settings.py`
- Test: `tests/test_pipeline/test_pipeline_config.py`

**Interfaces:**
- Produces: Unified YAML configuration for pipeline execution, memory thresholds, thread limits, and optional step enablement.

- [ ] **Step 1: Write test for Configuration Parsing**

```python
# tests/test_pipeline/test_pipeline_config.py
from config.settings import load_pipeline_config, PIPELINE_CONFIG_PATH

def test_pipeline_config_loads_defaults():
    config = load_pipeline_config()
    assert "concurrency" in config
    assert config["concurrency"]["max_workers"] >= 1
    assert "staging" in config
    assert "steps" in config
```

- [ ] **Step 2: Implement `config/pipeline_config.yaml` and parser in `config/settings.py`**

- [ ] **Step 3: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_pipeline/test_pipeline_config.py -v`
Expected: PASS

- [ ] **Step 4: Commit changes**

```bash
git add config/pipeline_config.yaml config/settings.py tests/test_pipeline/test_pipeline_config.py
git commit -m "feat(config): add pipeline_config.yaml and configuration loader"
```

---

### Task 3: Fix CLI Status / Reset Commands & `--enable` Argument Handling

**Files:**
- Modify: `main.py`
- Modify: `src/pipeline/core/duckdb_manager.py` (if any meta query updates needed)
- Test: `tests/test_pipeline/test_cli_commands.py`

**Interfaces:**
- Aligns `main.py` status/reset queries with `_pipeline_meta` table schema (`row_count`, `duration_secs`, `completed_at`, `status`).
- Passes `--enable` arguments to `PipelineContext.enabled_optional_steps`.

- [ ] **Step 1: Write tests for CLI Status and Reset execution**

- [ ] **Step 2: Fix `main.py` handlers and CLI arg parsing**

- [ ] **Step 3: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_pipeline/test_cli_commands.py -v`
Expected: PASS

- [ ] **Step 4: Commit changes**

```bash
git add main.py tests/test_pipeline/test_cli_commands.py
git commit -m "fix(cli): align status/reset queries with schema and pass enabled optional steps"
```

---

### Task 4: Delete Obsolete Duplicate Numbered Step Files & Update Legacy Tests

**Files:**
- Delete: `src/pipeline/steps/01_schema_init.py` through `15_sqlite_export.py`
- Modify: `tests/test_export.py`, `tests/test_pipeline_core.py`, `tests/test_pipeline_orchestrator.py`

**Interfaces:**
- Retains single source of truth in `src/pipeline/steps/` with 15 modern modular step files.
- Updates all remaining legacy test files to pass cleanly with V2 architecture.

- [ ] **Step 1: Delete all `01_`–`15_` files from `src/pipeline/steps/`**

- [ ] **Step 2: Update legacy test files to use V2 classes**

- [ ] **Step 3: Run full repository test suite**

Run: `PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: 100% PASS with 0 errors.

- [ ] **Step 4: Commit changes**

```bash
git add -A
git commit -m "chore(cleanup): remove legacy duplicate step files and align test suite"
```

---

### Task 5: Final End-to-End System Benchmark Verification

**Files:**
- Run: `PYTHONPATH=. python3 scripts/benchmark_pipeline.py`
- Run: `PYTHONPATH=. .venv/bin/pytest tests/ -v`

**Interfaces:**
- Validates full repository build, linting, and end-to-end benchmark execution.

- [ ] **Step 1: Run complete test suite**

- [ ] **Step 2: Verify zero test failures and confirm all 4 phases complete**

- [ ] **Step 3: Commit and prepare final walkthrough**

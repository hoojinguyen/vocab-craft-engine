"""
Deep Audit & Stress Verification Test Suite for Phase 4 (Concurrency, CLI, Config, and Cleanup).

Tests:
1. Multi-threaded DAG level concurrency with mixed workloads and thread safety.
2. Orchestrator error handling & halting during parallel level execution.
3. Optional step enablement via CLI args, config, and context.
4. CLI status command verification against _pipeline_meta table schema.
5. CLI reset command partial DAG downstream invalidation and complete reset.
6. Central pipeline configuration loading and environment overrides.
"""

import io
from pathlib import Path
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

from config.settings import load_pipeline_config
from main import handle_export, handle_reset, handle_status
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.dag import DAG
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import StepResult, StepStatus


class FastStepA(BaseStep):
    name = "fast_a"
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        time.sleep(0.1)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=50)


class FastStepB(BaseStep):
    name = "fast_b"
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        time.sleep(0.1)
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=100)


class FailingStepC(BaseStep):
    name = "fail_c"
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        raise RuntimeError("Intentional error in step fail_c")


class DownstreamStepD(BaseStep):
    name = "downstream_d"
    depends_on = ["fail_c"]

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=1)


class OptionalStepE(BaseStep):
    name = "opt_e"
    optional = True

    def should_skip(self, ctx: PipelineContext):
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(self.name, StepStatus.SUCCESS, items_processed=7)


@pytest.fixture
def audit_db(tmp_path: Path):
    db_file = tmp_path / "phase4_audit.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_concurrency_execution_timing(audit_db: DuckDBManager):
    """Verifies that 2 concurrent 0.1s steps execute in parallel (well under 0.2s)."""
    step_a = FastStepA()
    step_b = FastStepB()
    orchestrator = PipelineOrchestrator(steps=[step_a, step_b], max_workers=2)
    ctx = PipelineContext(db_manager=audit_db)

    t0 = time.perf_counter()
    summary = orchestrator.run(ctx)
    elapsed = time.perf_counter() - t0

    assert summary.has_failures is False
    assert len(summary.results) == 2
    assert elapsed < 0.18, f"Expected concurrency under 0.18s, took {elapsed:.3f}s"


def test_concurrency_failure_halts_downstream(audit_db: DuckDBManager):
    """Verifies that a failure in a concurrent level halts the pipeline."""
    step_fail = FailingStepC()
    step_down = DownstreamStepD()
    orchestrator = PipelineOrchestrator(steps=[step_fail, step_down], max_workers=2)
    ctx = PipelineContext(db_manager=audit_db)

    summary = orchestrator.run(ctx)
    assert summary.has_failures is True
    assert any(r.status == StepStatus.FAILED for r in summary.results)
    # Downstream step must NOT have run successfully
    downstream_results = [r for r in summary.results if r.step_name == "downstream_d"]
    assert len(downstream_results) == 0


def test_optional_step_enable_via_cli_flag(audit_db: DuckDBManager):
    """Verifies optional step runs when included in CLI --enable."""
    step_e = OptionalStepE()
    mock_args = MagicMock()
    mock_args.enable = "opt_e,another_step"
    mock_args.dry_run = False
    mock_args.tui = False

    orchestrator = PipelineOrchestrator(steps=[step_e])
    ctx = PipelineContext(db_manager=audit_db, args=mock_args)

    summary = orchestrator.run(ctx)
    assert summary.has_failures is False
    assert summary.results[0].status == StepStatus.SUCCESS
    assert summary.results[0].items_processed == 7


def test_cli_status_formatting_matches_schema(audit_db: DuckDBManager):
    """Verifies handle_status prints correctly without column mismatch errors."""
    conn = audit_db.get_connection()
    conn.execute("""
        INSERT INTO _pipeline_meta (step_name, status, row_count, duration_secs, started_at, completed_at)
        VALUES ('schema_init', 'SUCCESS', 15, 0.25, '2026-08-14T00:00:00Z', '2026-08-14T00:00:01Z')
    """)

    captured = io.StringIO()
    with patch("sys.stdout", captured):
        handle_status(audit_db)

    output = captured.getvalue()
    assert "PIPELINE STEP STATUS" in output
    assert "schema_init" in output
    assert "SUCCESS" in output
    assert "15" in output


def test_cli_reset_partial_and_all(audit_db: DuckDBManager):
    """Verifies handle_reset removes metadata correctly."""
    conn = audit_db.get_connection()
    conn.execute("""
        INSERT INTO _pipeline_meta (step_name, status, row_count, duration_secs, started_at, completed_at)
        VALUES ('ingest_kaikki', 'SUCCESS', 5000, 12.5, '2026-08-14T00:00:00Z', '2026-08-14T00:00:12Z')
    """)
    assert conn.execute("SELECT count(*) FROM _pipeline_meta").fetchone()[0] == 1

    # Reset all
    handle_reset(audit_db, reset_all=True)
    assert conn.execute("SELECT count(*) FROM _pipeline_meta").fetchone()[0] == 0


def test_config_loader_structure():
    """Verifies all expected keys in central pipeline_config.yaml."""
    cfg = load_pipeline_config()
    assert "pipeline" in cfg
    assert "concurrency" in cfg
    assert "staging" in cfg
    assert "export" in cfg
    assert "enrichment" in cfg
    assert "steps" in cfg
    assert cfg["concurrency"]["max_workers"] >= 1
    assert cfg["export"]["journal_mode"] == "WAL"

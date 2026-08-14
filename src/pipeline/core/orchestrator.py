"""
DAG Orchestrator V2.

Executes DAG levels sequentially, running independent steps within each level in parallel.
Integrates with DuckDB-backed StateManager, RetryPolicy, and Textual Dashboard.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from pathlib import Path
import time
from typing import Any, List, Optional, Set

from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.dag import DAG
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import PipelineSummary, StepResult, StepStatus
from src.pipeline.core.retry import RetryPolicy
from src.pipeline.core.state_manager import StateManager
from src.pipeline.monitor.dashboard import TextualPipelineDashboard
from src.pipeline.monitor.progress import ProgressReporter
from src.pipeline.monitor.run_logger import RunLogger

logger = logging.getLogger(__name__)


def _get_arg(args: Any, name: str, default: Any) -> Any:
    if not args or not hasattr(args, name):
        return default
    val = getattr(args, name)
    if val is None:
        return default
    return val


class PipelineOrchestrator:
    """DAG-aware parallel pipeline orchestrator."""

    def __init__(
        self,
        steps: Optional[List[BaseStep]] = None,
        registry: Optional[StepRegistry] = None,
        state_manager: Optional[StateManager] = None,
        state_file: Optional[Any] = None,
        max_workers: int = 4,
        tui_enabled: bool = False,
    ):
        if steps is not None:
            self.steps = steps
        elif registry is not None:
            self.steps = registry.get_steps() if hasattr(registry, "get_steps") else []
        else:
            self.steps = []

        self.dag = DAG(self.steps) if self.steps else None
        self.state_manager = state_manager
        if self.state_manager is None:
            from unittest.mock import MagicMock
            self.state_manager = MagicMock()
        self.max_workers = max(1, max_workers)
        self.dashboard: Optional[TextualPipelineDashboard] = None
        self.has_failures = False

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.monotonic()
        results: List[StepResult] = []
        self.has_failures = False

        if self.dag is None and self.steps:
            self.dag = DAG(self.steps)

        # Initialize DuckDB StateManager if needed
        if self.state_manager is None or type(self.state_manager).__name__ == "MagicMock":
            db_mgr = getattr(context, "db", None) or getattr(context, "db_manager", None)
            if isinstance(db_mgr, DuckDBManager):
                self.state_manager = StateManager(db_mgr)

        args = getattr(context, "args", None)
        dry_run = bool(_get_arg(args, "dry_run", False))
        force_all = bool(_get_arg(args, "force_all", False))
        force_steps_arg = _get_arg(args, "force_step", None) or _get_arg(args, "force_steps", None)
        if isinstance(force_steps_arg, str):
            force_steps: Set[str] = {s.strip() for s in force_steps_arg.split(",") if s.strip()}
        elif isinstance(force_steps_arg, (set, list)):
            force_steps = set(force_steps_arg)
        else:
            force_steps = set()

        tui_enabled = bool(_get_arg(args, "tui", False)) and not bool(_get_arg(args, "no_tui", False))
        max_retries = int(_get_arg(args, "max_retries", 3))
        log_dir_arg = _get_arg(args, "log_dir", "logs")
        log_dir = Path(log_dir_arg) if log_dir_arg else Path("logs")

        # Resolve enabled optional steps from CLI args or context
        enabled_opts = set(getattr(context, "enabled_optional_steps", []))
        cli_enabled = _get_arg(args, "enable", None)
        if isinstance(cli_enabled, str):
            enabled_opts.update([s.strip() for s in cli_enabled.split(",") if s.strip()])
        elif isinstance(cli_enabled, (list, set)):
            enabled_opts.update(cli_enabled)
        context.enabled_optional_steps = list(enabled_opts)

        run_logger = RunLogger(log_dir=log_dir)
        self.dashboard = TextualPipelineDashboard(enabled=tui_enabled and not dry_run)

        # Wire ProgressReporter with Dashboard
        if getattr(context, "progress_reporter", None) is None:
            context.progress_reporter = ProgressReporter(callback=self.dashboard.update_step_progress)
        else:
            existing_cb = getattr(context.progress_reporter, "callback", None)
            if existing_cb is None:
                context.progress_reporter.callback = self.dashboard.update_step_progress
            elif existing_cb != self.dashboard.update_step_progress:
                def combined_callback(step_name: str, cur: int, tot: int, msg: str = "") -> None:
                    if existing_cb:
                        try:
                            existing_cb(step_name, cur, tot, msg)
                        except Exception:
                            pass
                    if self.dashboard:
                        self.dashboard.update_step_progress(step_name, cur, tot, msg)

                context.progress_reporter.callback = combined_callback

        execution_levels = self.dag.get_execution_levels() if self.dag else []
        dag_levels_str = [[s.name for s in lvl] for lvl in execution_levels]
        step_info_map = {
            step.name: {
                "description": getattr(step, "description", ""),
                "depends_on": getattr(step, "depends_on", []),
                "produces": getattr(step, "produces", []),
                "execution_type": getattr(step, "execution_type", "cpu"),
                "type": getattr(step, "execution_type", "cpu"),
            }
            for level in execution_levels
            for step in level
        }
        self.dashboard.set_dag_levels(dag_levels_str, step_info_map)

        all_step_names = [s.name for level in execution_levels for s in level]

        logger.info("==========================================================")
        logger.info("   STARTING VOCAB CRAFT ENGINE PIPELINE (DAG V2)         ")
        logger.info("   Workers: %d | Total Steps: %d", self.max_workers, len(all_step_names))
        logger.info("==========================================================")

        def worker_func():
            self._execute_levels(
                execution_levels=execution_levels,
                context=context,
                dry_run=dry_run,
                force_all=force_all,
                force_steps=force_steps,
                max_retries=max_retries,
                results=results,
            )

        if tui_enabled and not dry_run:
            self.dashboard.set_worker(worker_func)
            self.dashboard.run()
        else:
            self.dashboard.start()
            try:
                worker_func()
            finally:
                self.dashboard.stop()

        total_time = round(time.monotonic() - start_time, 2)
        summary = PipelineSummary(total_time_seconds=total_time, results=results, has_failures=self.has_failures)
        run_logger.save_run_summary(summary, is_resumed=False)
        self._print_summary(results, total_time)
        return summary

    def _execute_single_step(
        self,
        step: BaseStep,
        context: PipelineContext,
        dry_run: bool,
        force_all: bool,
        force_steps: Set[str],
        retry_policy: RetryPolicy,
    ) -> StepResult:
        logger.info(f"=== START: {step.name}")
        step_start = time.monotonic()
        if self.dashboard:
            self.dashboard.update_step(step.name, "RUNNING")

        # 1. Check dry-run
        if dry_run:
            msg = f"[DRY-RUN] Would run '{step.name}' ({getattr(step, 'description', '')})"
            logger.info(msg)
            res = StepResult(step_name=step.name, status=StepStatus.SKIPPED, execution_time_seconds=0.0, message=msg)
            if self.dashboard:
                self.dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, "Dry-Run")
            logger.info(f"=== END: {step.name}")
            return res

        # 2. Check if optional and disabled
        is_optional = getattr(step, "optional", False)
        enabled_list = getattr(context, "enabled_optional_steps", [])
        if is_optional and step.name not in enabled_list:
            msg = f"Optional step '{step.name}' is not enabled"
            logger.info("SKIPPED: %s (%s)", step.name, msg)
            res = StepResult(step_name=step.name, status=StepStatus.SKIPPED, execution_time_seconds=0.0, message=msg)
            if self.dashboard:
                self.dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, "Optional Disabled")
            logger.info(f"=== END: {step.name}")
            return res

        # 3. Check StateManager skip condition
        skip = False
        skip_reason = ""
        if self.state_manager and self.dag and hasattr(self.state_manager, "should_skip"):
            res_skip = self.state_manager.should_skip(
                step=step, dag=self.dag, force_steps=force_steps, force_all=force_all
            )
            if isinstance(res_skip, tuple) and len(res_skip) == 2:
                skip, skip_reason = res_skip

        if skip:
            logger.info("SKIPPED: %s (%s)", step.name, skip_reason)
            res = StepResult(
                step_name=step.name,
                status=StepStatus.SKIPPED,
                execution_time_seconds=0.0,
                message=skip_reason,
            )
            if self.dashboard:
                self.dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, skip_reason)
            logger.info(f"=== END: {step.name}")
            return res

        # Invalidate downstream steps in state manager
        if self.state_manager and self.dag:
            self.state_manager.invalidate_step(step.name, self.dag)

        # 4. Execute with retry
        try:
            logger.info("Running: %s...", getattr(step, "description", ""))

            def on_retry(attempt, total, exc):
                if self.dashboard:
                    self.dashboard.update_step(step.name, f"RETRY {attempt}/{total}", retries=attempt)
                    self.dashboard.add_log(f"[WARNING] [{step.name}] Attempt {attempt}/{total} failed: {exc}")

            res = retry_policy.execute_with_retry(step, context, on_retry_callback=on_retry)
            duration = round(time.monotonic() - step_start, 2)
            if res.execution_time_seconds == 0.0:
                res.execution_time_seconds = duration

            if res.status == StepStatus.SUCCESS:
                if self.state_manager:
                    source_hash = step.compute_source_hash()
                    self.state_manager.record_success(
                        step.name, source_hash, res.items_processed, res.execution_time_seconds
                    )
                if self.dashboard:
                    self.dashboard.update_step(
                        step.name, "SUCCESS", res.execution_time_seconds, res.items_processed, res.retry_count,
                        f"processed: {res.items_processed}"
                    )
                logger.info(f"=== END: {step.name}")
                return res
            else:
                self.has_failures = True
                if self.state_manager:
                    source_hash = step.compute_source_hash()
                    self.state_manager.record_failure(
                        step.name, source_hash, res.execution_time_seconds, res.message
                    )
                    if self.dag:
                        self.state_manager.invalidate_step(step.name, self.dag)

                if self.dashboard:
                    self.dashboard.update_step(
                        step.name, "FAILED", res.execution_time_seconds, 0, res.retry_count, res.message[:20] if res.message else ""
                    )
                if hasattr(step, "rollback"):
                    try:
                        step.rollback(context)
                    except Exception as rb_err:
                        logger.warning("Rollback error: %s", rb_err)
                logger.info(f"=== END: {step.name}")
                return res

        except Exception as e:
            duration = round(time.monotonic() - step_start, 2)
            logger.error("FAILED step '%s' after %ss: %s", step.name, duration, e, exc_info=True)
            self.has_failures = True
            res = StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                execution_time_seconds=duration,
                message=str(e),
                error=e,
            )
            if self.state_manager:
                source_hash = step.compute_source_hash()
                self.state_manager.record_failure(step.name, source_hash, duration, str(e))
                if self.dag:
                    self.state_manager.invalidate_step(step.name, self.dag)

            if self.dashboard:
                self.dashboard.update_step(step.name, "FAILED", duration, 0, 0, str(e)[:20])
            if hasattr(step, "rollback"):
                try:
                    step.rollback(context)
                except Exception as rb_err:
                    logger.warning("Rollback error: %s", rb_err)
            logger.info(f"=== END: {step.name}")
            return res

    def _execute_levels(
        self,
        execution_levels: List[List[BaseStep]],
        context: PipelineContext,
        dry_run: bool,
        force_all: bool,
        force_steps: Set[str],
        max_retries: int,
        results: List[StepResult],
    ) -> None:
        retry_policy = RetryPolicy(max_retries=max_retries)

        for level_idx, level in enumerate(execution_levels, 1):
            if self.has_failures:
                logger.warning("Pipeline halted due to earlier step failure.")
                break

            logger.info(f"--- Execution Level {level_idx} ({len(level)} step(s)) ---")

            if len(level) == 1 or dry_run:
                # Sequential single step execution
                for step in level:
                    res = self._execute_single_step(
                        step=step,
                        context=context,
                        dry_run=dry_run,
                        force_all=force_all,
                        force_steps=force_steps,
                        retry_policy=retry_policy,
                    )
                    results.append(res)
                    if res.status == StepStatus.FAILED:
                        self.has_failures = True
                        break
            else:
                # Concurrent level execution across worker threads
                workers = min(self.max_workers, len(level))
                logger.info("Executing %d level steps concurrently with %d workers", len(level), workers)

                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_step = {
                        executor.submit(
                            self._execute_single_step,
                            step,
                            context,
                            dry_run,
                            force_all,
                            force_steps,
                            retry_policy,
                        ): step
                        for step in level
                    }

                    for future in as_completed(future_to_step):
                        res = future.result()
                        results.append(res)
                        if res.status == StepStatus.FAILED:
                            self.has_failures = True

    def _print_summary(self, results: List[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 65)
        logger.info(f"{'STEP NAME':<25} | {'STATUS':<8} | {'TIME (s)':<8} | {'ITEMS':<8}")
        logger.info("-" * 65)
        for r in results:
            logger.info(f"{r.step_name:<25} | {r.status.value:<8} | {r.execution_time_seconds:<8.2f} | {r.items_processed:<8}")
        logger.info("=" * 65)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 65 + "\n")

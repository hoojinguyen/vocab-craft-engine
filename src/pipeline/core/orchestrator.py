import logging
import time
from pathlib import Path
import re
from typing import Any

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.result import PipelineSummary, StepResult, StepStatus
from src.pipeline.core.retry import RetryPolicy
from src.pipeline.core.state_manager import StateManager
from src.pipeline.monitor.dashboard import TextualPipelineDashboard
from src.pipeline.monitor.run_logger import RunLogger

logger = logging.getLogger(__name__)


def _get_arg(args: Any, name: str, default: Any) -> Any:
    if not args or not hasattr(args, name):
        return default
    val = getattr(args, name)
    if val is None:
        return default
    if not isinstance(val, (bool, int, float, str, list, dict, set, tuple, Path)):
        return default
    return val


class PipelineOrchestrator:
    def __init__(self, registry: StepRegistry, state_file: Path = Path(".pipeline_state.json")):
        self.registry = registry
        self.state_manager = StateManager(state_file=state_file)
        self.dashboard: TextualPipelineDashboard | None = None
        self.has_failures = False

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.monotonic()
        results: list[StepResult] = []
        self.has_failures = False

        args = getattr(context, "args", None)
        dry_run = bool(_get_arg(args, "dry_run", False))
        resume = bool(_get_arg(args, "resume", False))
        tui_enabled = bool(_get_arg(args, "tui", True))
        max_retries = int(_get_arg(args, "max_retries", 3))
        log_dir_arg = _get_arg(args, "log_dir", "logs")
        log_dir = Path(log_dir_arg) if log_dir_arg else Path("logs")

        run_logger = RunLogger(log_dir=log_dir)
        self.dashboard = TextualPipelineDashboard(enabled=tui_enabled and not dry_run)

        if not dry_run and not resume:
            self.state_manager.clear_state()

        previous_state = self.state_manager.load_state() if resume else {}

        include_steps = _get_arg(args, "steps", None)
        if isinstance(include_steps, str):
            include_steps = [s.strip() for s in include_steps.split(",") if s.strip()]

        skip_steps = _get_arg(args, "skip_steps", None)
        if isinstance(skip_steps, str):
            skip_steps = [s.strip() for s in skip_steps.split(",") if s.strip()]

        steps_to_run = self.registry.filter_steps(include_steps=include_steps, skip_steps=skip_steps)
        self.dashboard.set_steps([s.name for s in steps_to_run])

        logger.info("==========================================================")
        logger.info("   STARTING VOCAB CRAFT ENGINE PIPELINE EXECUTION        ")
        logger.info("==========================================================")

        def worker_func():
            self._execute_pipeline(
                steps_to_run, context, dry_run, resume, previous_state, max_retries, results
            )

        if tui_enabled and not dry_run:
            self.dashboard.set_worker(worker_func)
            # This will block until the app is closed by the user
            self.dashboard.run()
        else:
            self.dashboard.start()
            try:
                worker_func()
            finally:
                self.dashboard.stop()

        total_time = round(time.monotonic() - start_time, 2)
        summary = PipelineSummary(total_time_seconds=total_time, results=results, has_failures=self.has_failures)
        run_logger.save_run_summary(summary, is_resumed=resume)
        self._print_summary(results, total_time)
        return summary

    def _execute_pipeline(
        self, steps_to_run, context, dry_run, resume, previous_state, max_retries, results
    ) -> None:
        retry_policy = RetryPolicy(max_retries=max_retries)

        try:
            for idx, step in enumerate(steps_to_run, 1):
                self.dashboard.current_step_idx = idx
                logger.info(f"=== START: {step.name}")
                
                step_start = time.monotonic()
                self.dashboard.update_step(step.name, "RUNNING")

                if resume and previous_state.get(step.name, {}).get("status") == "SUCCESS":
                    msg = "Skipped via --resume (already completed in previous run)"
                    logger.info("%s", msg)
                    prev = previous_state[step.name]
                    res = StepResult(
                        step_name=step.name,
                        status=StepStatus.SKIPPED,
                        execution_time_seconds=prev.get("duration", 0.0),
                        items_processed=prev.get("items", 0),
                        message=msg
                    )
                    results.append(res)
                    self.dashboard.update_step(step.name, "SKIPPED", res.execution_time_seconds, res.items_processed, 0, "Resumed")
                    logger.info(f"=== END: {step.name}")
                    continue

                try:
                    if dry_run:
                        try:
                            skip, reason = step.should_skip(context)
                        except Exception as skip_err:
                            skip, reason = False, f"Table/DB check skipped in dry-run ({skip_err})"

                        msg = f"[DRY-RUN] Would run '{step.name}' ({getattr(step, 'description', '')}). Dry-run mode. Skip status: {skip} ({reason})"
                        logger.info(msg)
                        res = StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED,
                            execution_time_seconds=0.0,
                            message=msg
                        )
                        results.append(res)
                        self.dashboard.update_step(step.name, "SKIPPED", 0.0, 0, 0, "Dry-Run")
                        logger.info(f"=== END: {step.name}")
                        continue

                    skip, reason = step.should_skip(context)

                    if skip:
                        skipped_items = 0
                        match = re.search(r'([0-9,]+)', reason)
                        if match:
                            try:
                                skipped_items = int(match.group(1).replace(',', ''))
                            except ValueError:
                                pass
                                
                        logger.info("SKIPPED: %s", reason)
                        res = StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED,
                            execution_time_seconds=0.0,
                            items_processed=skipped_items,
                            message=reason
                        )
                        results.append(res)
                        self.dashboard.update_step(step.name, "SKIPPED", 0.0, skipped_items, 0, reason)
                        logger.info(f"=== END: {step.name}")
                        continue

                    logger.info("Running: %s...", getattr(step, "description", ""))

                    def on_retry(attempt, total, exc):
                        self.dashboard.update_step(step.name, f"RETRY {attempt}/{total}", retries=attempt)
                        self.dashboard.add_log(f"[WARNING] [{step.name}] Attempt {attempt}/{total} failed: {exc}")

                    res = retry_policy.execute_with_retry(step, context, on_retry_callback=on_retry)
                    duration = round(time.monotonic() - step_start, 2)
                    if res.execution_time_seconds == 0.0:
                        res.execution_time_seconds = duration
                    results.append(res)

                    if res.status == StepStatus.SUCCESS:
                        try:
                            self.state_manager.save_step_status(step.name, "SUCCESS", res.execution_time_seconds, res.items_processed)
                        except Exception as save_err:
                            logger.warning("Warning: Failed to save step status to state manager: %s", save_err)
                        self.dashboard.update_step(
                            step.name, "SUCCESS", res.execution_time_seconds, res.items_processed, res.retry_count,
                            f"processed: {res.items_processed}"
                        )
                        logger.info(f"=== END: {step.name}")
                    else:
                        self.has_failures = True
                        try:
                            self.state_manager.save_step_status(step.name, "FAILED", res.execution_time_seconds, 0)
                        except Exception as save_err:
                            logger.warning("Warning: Failed to save step status to state manager: %s", save_err)
                        self.dashboard.update_step(step.name, "FAILED", res.execution_time_seconds, 0, res.retry_count, res.message[:20] if res.message else "")
                        if hasattr(step, "rollback"):
                            try:
                                step.rollback(context)
                            except Exception as rb_err:
                                logger.warning("Rollback warning: %s", rb_err)
                        logger.info(f"=== END: {step.name}")
                        break

                except Exception as e:
                    duration = round(time.monotonic() - step_start, 2)
                    logger.error("FAILED after %ss: %s", duration, e, exc_info=True)
                    self.has_failures = True
                    res = StepResult(
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        execution_time_seconds=duration,
                        message=str(e),
                        error=e
                    )
                    results.append(res)
                    self.dashboard.update_step(step.name, "FAILED", duration, 0, 0, str(e)[:20])
                    try:
                        self.state_manager.save_step_status(step.name, "FAILED", duration, 0)
                    except Exception as save_err:
                        logger.warning("Warning: Failed to save step status to state manager: %s", save_err)
                    if hasattr(step, "rollback"):
                        try:
                            step.rollback(context)
                        except Exception as rollback_err:
                            logger.warning("Rollback warning: %s", rollback_err)
                    logger.info(f"=== END: {step.name}")
                    break
        finally:
            pass

    def _print_summary(self, results: list[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 65)
        logger.info(f"{'STEP NAME':<25} | {'STATUS':<8} | {'TIME (s)':<8} | {'ITEMS':<8}")
        logger.info("-" * 65)
        for r in results:
            logger.info(f"{r.step_name:<25} | {r.status.value:<8} | {r.execution_time_seconds:<8.2f} | {r.items_processed:<8}")
        logger.info("=" * 65)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 65 + "\n")

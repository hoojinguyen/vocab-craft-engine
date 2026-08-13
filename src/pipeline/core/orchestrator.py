import time
import logging
from pathlib import Path
from typing import List, Optional

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus, StepResult, PipelineSummary
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.state_manager import StateManager

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self, registry: StepRegistry, state_file: Path = Path(".pipeline_state.json")):
        self.registry = registry
        self.state_manager = StateManager(state_file=state_file)

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.time()
        results: List[StepResult] = []

        include_steps = getattr(context.args, "steps", None)
        if isinstance(include_steps, str):
            include_steps = [s.strip() for s in include_steps.split(",") if s.strip()]

        skip_steps = getattr(context.args, "skip_steps", None)
        if isinstance(skip_steps, str):
            skip_steps = [s.strip() for s in skip_steps.split(",") if s.strip()]

        steps_to_run = self.registry.filter_steps(include_steps=include_steps, skip_steps=skip_steps)
        dry_run = getattr(context.args, "dry_run", False)

        logger.info("==========================================================")
        logger.info("   STARTING VOCAB CRAFT ENGINE PIPELINE EXECUTION        ")
        logger.info("==========================================================")

        has_failures = False
        for step in steps_to_run:
            step_start = time.time()
            skip, reason = step.should_skip(context)

            if dry_run:
                msg = f"[DRY-RUN] Dry-run mode: Would run '{step.name}' ({step.description}). Skip status: {skip} ({reason})"
                logger.info(msg)
                res = StepResult(
                    step_name=step.name,
                    status=StepStatus.SKIPPED,
                    execution_time_seconds=0.0,
                    message=msg
                )
                results.append(res)
                self.state_manager.save_step_status(step.name, "SKIPPED", 0.0, 0)
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
                self.state_manager.save_step_status(step.name, "SKIPPED", 0.0, 0)
                continue

            logger.info("[%s] Running: %s...", step.name, step.description)
            try:
                res = step.run(context)
                duration = round(time.time() - step_start, 2)
                res.execution_time_seconds = duration
                results.append(res)
                self.state_manager.save_step_status(step.name, res.status.value, duration, res.items_processed)
                if res.status == StepStatus.FAILED:
                    has_failures = True
            except Exception as e:
                duration = round(time.time() - step_start, 2)
                logger.error("[%s] FAILED after %ss: %s", step.name, duration, e, exc_info=True)
                step.rollback(context)
                res = StepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    execution_time_seconds=duration,
                    message=str(e),
                    error=e
                )
                results.append(res)
                self.state_manager.save_step_status(step.name, "FAILED", duration, 0)
                has_failures = True
                break

        total_time = round(time.time() - start_time, 2)
        self._print_summary(results, total_time)
        return PipelineSummary(total_time_seconds=total_time, results=results, has_failures=has_failures)

    def _print_summary(self, results: List[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 65)
        logger.info(f"{'STEP NAME':<25} | {'STATUS':<8} | {'TIME (s)':<8} | {'ITEMS':<8}")
        logger.info("-" * 65)
        for r in results:
            logger.info(f"{r.step_name:<25} | {r.status.value:<8} | {r.execution_time_seconds:<8.2f} | {r.items_processed:<8}")
        logger.info("=" * 65)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 65 + "\n")

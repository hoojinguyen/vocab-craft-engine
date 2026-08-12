"""DAG-based pipeline executor with parallel step execution."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, Set, Optional, Any

from src.pipeline.context import PipelineContext
from src.pipeline.registry import CheckpointRegistry

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    name: str
    func: Callable[[PipelineContext], None]
    depends: Set[str] = field(default_factory=set)


class DAGExecutor:
    """Executes pipeline steps respecting dependency order. Independent steps run in parallel."""

    def __init__(self, registry: Optional[CheckpointRegistry] = None):
        self._steps: Dict[str, PipelineStep] = {}
        self.registry = registry

    def add_step(self, name: str, func: Callable[[PipelineContext], None],
                 depends: Optional[Set[str]] = None) -> "DAGExecutor":
        self._steps[name] = PipelineStep(name=name, func=func, depends=depends or set())
        return self

    def execute(self, context: PipelineContext, force_reset: bool = False):
        if force_reset and self.registry:
            self.registry.clear_all()

        completed: Set[str] = set()
        self._load_checkpoints(completed, context)

        while True:
            ready = self._find_ready(completed)
            if not ready:
                break

            logger.info("[DAG] Executing steps: %s", sorted(ready))
            self._execute_parallel(ready, context, completed)

        logger.info("[DAG] All steps complete.")

    def _execute_parallel(self, ready: Set[str], context: PipelineContext, completed: Set[str]):
        workers = min(len(ready), 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._run_step, name, context): name
                for name in ready
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                    completed.add(name)
                    if self.registry:
                        self.registry.mark_done(name)
                except Exception:
                    logger.exception("[DAG] Step '%s' failed", name)
                    raise

    def _run_step(self, name: str, context: PipelineContext):
        step = self._steps[name]
        start = time.time()
        logger.info("[DAG] Starting step: %s", name)
        step.func(context)
        elapsed = time.time() - start
        logger.info("[DAG] Step '%s' completed in %.2fs", name, elapsed)

    def _find_ready(self, completed: Set[str]) -> Set[str]:
        return {
            name for name, step in self._steps.items()
            if name not in completed and step.depends.issubset(completed)
        }

    def _load_checkpoints(self, completed: Set[str], context: PipelineContext):
        if not self.registry:
            return
        for name in self._steps:
            if self.registry.is_done(name):
                completed.add(name)
                logger.info("[DAG] Skipping '%s' (checkpoint found)", name)

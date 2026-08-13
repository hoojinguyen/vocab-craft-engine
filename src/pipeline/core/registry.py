from typing import List, Dict, Optional
from src.pipeline.core.base_step import BaseStep

class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []
        self._step_map: Dict[str, BaseStep] = {}

    def register(self, step: BaseStep) -> None:
        self._steps.append(step)
        self._step_map[step.name] = step

    def get_all_steps(self) -> List[BaseStep]:
        return list(self._steps)

    def get_step(self, name: str) -> Optional[BaseStep]:
        return self._step_map.get(name)

    def filter_steps(
        self,
        include_steps: Optional[List[str]] = None,
        skip_steps: Optional[List[str]] = None
    ) -> List[BaseStep]:
        steps = list(self._steps)
        if include_steps:
            inc_set = set(include_steps)
            steps = [s for s in steps if s.name in inc_set]
        if skip_steps:
            skip_set = set(skip_steps)
            steps = [s for s in steps if s.name not in skip_set]
        return steps

from abc import ABC, abstractmethod
from typing import Tuple
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult


class BaseStep(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        """Determines whether to skip execution."""
        pass

    @abstractmethod
    def run(self, context: PipelineContext) -> StepResult:
        """Executes the core step logic."""
        pass

    def rollback(self, context: PipelineContext) -> None:
        """Optional cleanup routine if step execution fails."""
        pass

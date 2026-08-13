"""
Base class for all pipeline steps (V2).

Steps declare their dependencies, outputs, execution type, and source files
for DAG-based resolution, parallel orchestration, and content-hash caching.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult


class BaseStep(ABC):
    """Abstract base class for pipeline execution steps."""

    name: str = ""
    description: str = ""
    depends_on: list[str] = []
    produces: list[str] = []
    optional: bool = False
    execution_type: str = "cpu"  # "cpu" for ProcessPoolExecutor, "io" for asyncio
    source_files: list[Path] = []

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

    def compute_source_hash(self) -> str:
        """Compute SHA256 (first 16 chars) based on source file attributes.

        If source_files is empty, hashes the class name.
        """
        hasher = hashlib.sha256()
        if not self.source_files:
            hasher.update(self.name.encode("utf-8"))
        else:
            for filepath in sorted(self.source_files):
                path = Path(filepath)
                if path.exists():
                    stat = path.stat()
                    info = f"{path.name}:{stat.st_size}:{stat.st_mtime}"
                    hasher.update(info.encode("utf-8"))
                else:
                    hasher.update(f"{path.name}:missing".encode("utf-8"))
        return hasher.hexdigest()[:16]

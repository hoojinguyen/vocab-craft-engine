from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class StepStatus(Enum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class StepResult:
    step_name: str
    status: StepStatus
    execution_time_seconds: float = 0.0
    items_processed: int = 0
    message: str = ""
    error: Optional[Exception] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineSummary:
    total_time_seconds: float
    results: List[StepResult]
    has_failures: bool

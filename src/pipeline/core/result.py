from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class StepStatus(Enum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


@dataclass
class StepResult:
    step_name: str
    status: StepStatus
    execution_time_seconds: float = 0.0
    items_processed: int = 0
    message: str = ""
    error: Optional[Exception] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    error_traceback: Optional[str] = None
    data_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineSummary:
    total_time_seconds: float
    results: List[StepResult]
    has_failures: bool

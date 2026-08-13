from dataclasses import dataclass, field
from typing import Any, Dict
from src.db.staging_db import DatabaseManager


@dataclass
class PipelineContext:
    db_manager: DatabaseManager
    args: Any
    shared_data: Dict[str, Any] = field(default_factory=dict)

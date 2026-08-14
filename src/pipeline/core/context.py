"""
Pipeline Context V2.

Carries database manager, CLI args, enabled optional steps, and shared transient state across steps.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.db.duckdb_manager import DuckDBManager
from src.db.staging_db import DatabaseManager


@dataclass
class PipelineContext:
    """Execution context passed to each pipeline step."""

    db_manager: Union[DuckDBManager, DatabaseManager]
    args: Any = None
    output_dir: Optional[Path] = None
    enabled_optional_steps: List[str] = field(default_factory=list)
    shared_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def db(self) -> Union[DuckDBManager, DatabaseManager]:
        """Convenience alias for db_manager."""
        return self.db_manager

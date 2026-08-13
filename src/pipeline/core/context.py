"""
Pipeline Context V2.

Carries database manager, CLI args, and shared transient state across steps.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Union

from src.db.duckdb_manager import DuckDBManager
from src.db.staging_db import DatabaseManager


@dataclass
class PipelineContext:
    """Execution context passed to each pipeline step."""

    db_manager: Union[DuckDBManager, DatabaseManager]
    args: Any = None
    shared_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def db(self) -> Union[DuckDBManager, DatabaseManager]:
        """Convenience alias for db_manager."""
        return self.db_manager

"""Base class for streaming data ingestors."""

from abc import ABC, abstractmethod
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


class BaseIngestor(ABC):
    @abstractmethod
    def ingest(self, db_mgr: DuckDBManager, source_path: Path) -> int:
        """Stream data from source_path into DuckDB staging tables."""
        pass

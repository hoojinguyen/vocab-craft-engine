"""Fast Orjson Dataset JSON Exporter."""

from pathlib import Path
import orjson
from src.db.duckdb_manager import DuckDBManager


class JsonExporter:
    def export(self, db_mgr: DuckDBManager, target_path: Path) -> int:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        words = db_mgr.count_rows("words")

        data = {"vocab_count": words, "status": "complete"}
        target_path.write_bytes(orjson.dumps(data))
        return words

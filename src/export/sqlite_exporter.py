"""Zero-Copy DuckDB -> SQLite Export Bridge."""

import logging
import sqlite3
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

EXPORT_TABLES = [
    "words",
    "definitions",
    "sentences",
    "word_sentences",
    "phrases",
    "phrase_sentences",
    "word_relations",
    "word_topics",
    "reflex_drills",
    "dialogue_trees",
    "dialogue_nodes",
]


class SQLiteExporter:
    def export(self, db_mgr: DuckDBManager, target_sqlite_path: Path) -> int:
        target_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if target_sqlite_path.exists():
            target_sqlite_path.unlink()

        conn = db_mgr.get_connection()
        total_rows = 0

        # Create target SQLite db
        s_conn = sqlite3.connect(target_sqlite_path)
        s_conn.execute("PRAGMA journal_mode=WAL;")
        s_conn.close()

        # DuckDB ATTACH SQLite
        conn.execute(f"ATTACH '{target_sqlite_path}' AS output (TYPE sqlite);")

        for table in EXPORT_TABLES:
            try:
                conn.execute(f"CREATE TABLE output.{table} AS SELECT * FROM main.{table};")
                count = db_mgr.count_rows(table)
                total_rows += count
            except Exception as e:
                logger.warning("Table export notice for %s: %s", table, e)

        conn.execute("DETACH output;")
        return total_rows

"""
DuckDB Staging Database Manager.

Provides connection management, batch inserts with dedup, and internal
pipeline state/cache table operations for the DAG-based pipeline.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.db.schema import INTERNAL_SCHEMA, INTERNAL_TABLES, STAGING_SCHEMA

logger = logging.getLogger(__name__)


class DuckDBManager:
    """Manages a DuckDB staging database for the pipeline."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_schema(self) -> None:
        """Create all staging and internal tables."""
        conn = self.get_connection()
        conn.execute(STAGING_SCHEMA)
        conn.execute(INTERNAL_SCHEMA)
        logger.info("DuckDB schema initialized at %s", self.db_path)

    # ---- Batch Operations ------------------------------------------------

    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert rows into table with ON CONFLICT DO NOTHING for dedup.

        Returns the number of rows inserted (new count - old count).
        """
        if not rows:
            return 0
        conn = self.get_connection()
        count_before = self.count_rows(table)
        columns = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})"
        values = [tuple(row.get(c) for c in columns) for row in rows]
        conn.executemany(sql, values)
        count_after = self.count_rows(table)
        return count_after - count_before

    def count_rows(self, table: str) -> int:
        conn = self.get_connection()
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        return row[0] if row else 0

    # ---- Pipeline Meta ---------------------------------------------------

    def get_step_meta(self, step_name: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT step_name, status, source_hash, row_count, "
            "started_at, completed_at, duration_secs, error_message "
            "FROM _pipeline_meta WHERE step_name = ?",
            [step_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "step_name": row[0],
            "status": row[1],
            "source_hash": row[2],
            "row_count": row[3],
            "started_at": row[4],
            "completed_at": row[5],
            "duration_secs": row[6],
            "error_message": row[7],
        }

    def save_step_meta(
        self,
        step_name: str,
        status: str,
        source_hash: str | None = None,
        row_count: int = 0,
        duration_secs: float = 0.0,
        error_message: str | None = None,
    ) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _pipeline_meta "
            "(step_name, status, source_hash, row_count, started_at, completed_at, "
            "duration_secs, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [step_name, status, source_hash, row_count, now, now, duration_secs, error_message],
        )

    # ---- Batch Checkpoints -----------------------------------------------

    def get_last_checkpoint(self, step_name: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT batch_id, rows_written, checkpoint_data, created_at "
            "FROM _batch_checkpoints WHERE step_name = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [step_name],
        ).fetchone()
        if row is None:
            return None
        return {
            "batch_id": row[0],
            "rows_written": row[1],
            "checkpoint_data": row[2],
            "created_at": row[3],
        }

    def save_checkpoint(
        self, step_name: str, batch_id: str, rows_written: int, data: str | None = None
    ) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _batch_checkpoints "
            "(step_name, batch_id, rows_written, checkpoint_data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [step_name, batch_id, rows_written, data, now],
        )

    def clear_checkpoints(self, step_name: str) -> None:
        conn = self.get_connection()
        conn.execute("DELETE FROM _batch_checkpoints WHERE step_name = ?", [step_name])

    # ---- Translation Cache -----------------------------------------------

    def get_translation(self, text: str) -> str | None:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT target_text FROM _translation_cache WHERE source_text = ?",
            [text],
        ).fetchone()
        return row[0] if row else None

    def save_translation(self, text: str, translated: str, translator: str) -> None:
        conn = self.get_connection()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO _translation_cache "
            "(source_text, target_text, translator, created_at) VALUES (?, ?, ?, ?)",
            [text, translated, translator, now],
        )

    def get_translations_batch(self, texts: list[str]) -> dict[str, str]:
        if not texts:
            return {}
        conn = self.get_connection()
        placeholders = ", ".join(["?"] * len(texts))
        rows = conn.execute(
            f"SELECT source_text, target_text FROM _translation_cache "
            f"WHERE source_text IN ({placeholders})",
            texts,
        ).fetchall()
        return {row[0]: row[1] for row in rows}

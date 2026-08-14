"""
DuckDB Staging Database Manager.

Provides thread-safe connection management, batch inserts with dedup, and internal
pipeline state/cache table operations for the DAG-based pipeline.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

import duckdb

from src.db.schema import INTERNAL_SCHEMA, INTERNAL_TABLES, STAGING_SCHEMA

logger = logging.getLogger(__name__)


class DuckDBManager:
    """Manages a DuckDB staging database for the pipeline."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.RLock()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                self._conn = duckdb.connect(str(self.db_path))
                self._conn.execute("PRAGMA threads = 4;")
                self._conn.execute("PRAGMA memory_limit = '4GB';")
                temp_dir = self.db_path.parent / "duckdb_temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                self._conn.execute(f"PRAGMA temp_directory = '{temp_dir}';")
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def init_schema(self) -> None:
        """Create all staging and internal tables."""
        with self._lock:
            conn = self.get_connection()
            conn.execute(STAGING_SCHEMA)
            conn.execute(INTERNAL_SCHEMA)
            logger.info("DuckDB schema initialized at %s", self.db_path)

    # ---- Batch Operations ------------------------------------------------

    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert rows into table with ON CONFLICT DO NOTHING for dedup."""
        return self.insert_batch_fast(table, rows)

    def insert_batch_fast(self, table: str, rows: list[dict[str, Any]]) -> int:
        """High-speed batch insertion using PyArrow Table zero-copy registration in DuckDB."""
        if not rows:
            return 0
        import pyarrow as pa

        with self._lock:
            conn = self.get_connection()
            arrow_table = pa.Table.from_pylist(rows)
            col_names = arrow_table.column_names
            col_str = ", ".join(col_names)
            conn.register("_tmp_arrow_batch", arrow_table)
            conn.execute(f"INSERT OR IGNORE INTO {table} ({col_str}) SELECT {col_str} FROM _tmp_arrow_batch")
            conn.unregister("_tmp_arrow_batch")
            return arrow_table.num_rows

    def insert_arrow(self, table: str, arrow_table) -> int:
        """Insert a PyArrow table directly into DuckDB without python conversion."""
        if arrow_table is None or arrow_table.num_rows == 0:
            return 0

        with self._lock:
            conn = self.get_connection()
            col_names = arrow_table.column_names
            col_str = ", ".join(col_names)
            conn.register("_tmp_arrow_batch", arrow_table)
            conn.execute(f"INSERT OR IGNORE INTO {table} ({col_str}) SELECT {col_str} FROM _tmp_arrow_batch")
            conn.unregister("_tmp_arrow_batch")
            return arrow_table.num_rows

    def count_rows(self, table: str) -> int:
        with self._lock:
            conn = self.get_connection()
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            return row[0] if row else 0

    # ---- Pipeline Meta ---------------------------------------------------

    def get_step_meta(self, step_name: str) -> dict[str, Any] | None:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        self,
        step_name: str,
        batch_id: int,
        rows_written: int,
        checkpoint_data: str | None = None,
    ) -> None:
        with self._lock:
            conn = self.get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO _batch_checkpoints "
                "(step_name, batch_id, rows_written, checkpoint_data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [step_name, batch_id, rows_written, checkpoint_data, datetime.now(timezone.utc)],
            )

    def clear_checkpoints(self, step_name: str) -> None:
        with self._lock:
            conn = self.get_connection()
            conn.execute("DELETE FROM _batch_checkpoints WHERE step_name = ?", [step_name])

    # ---- Cache Operations ------------------------------------------------

    def lookup_ipa(self, word: str) -> dict[str, Any] | None:
        """Lookup cached IPA UK and US values for a word."""
        with self._lock:
            conn = self.get_connection()
            row = conn.execute(
                "SELECT ipa_uk, ipa_us, source FROM _ipa_cache WHERE word = ?",
                [word],
            ).fetchone()
            if row is None:
                return None
            return {"ipa_uk": row[0], "ipa_us": row[1], "source": row[2]}

    def get_ipa(self, word: str) -> dict[str, Any] | None:
        """Alias for lookup_ipa."""
        return self.lookup_ipa(word)

    def save_ipa(
        self,
        word: str,
        ipa_uk: str | None = None,
        ipa_us: str | None = None,
        source: str | None = None,
    ) -> None:
        """Save word IPA pronunciation to cache."""
        with self._lock:
            conn = self.get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO _ipa_cache (word, ipa_uk, ipa_us, source) VALUES (?, ?, ?, ?)",
                [word, ipa_uk, ipa_us, source],
            )

    def get_translation(self, text: str) -> str | None:
        """Fetch cached translation for a single text string."""
        with self._lock:
            conn = self.get_connection()
            row = conn.execute(
                "SELECT target_text FROM _translation_cache WHERE source_text = ?",
                [text],
            ).fetchone()
            return row[0] if row else None

    def save_translation(
        self,
        source_text: str,
        target_text: str,
        engine: str = "argos",
        translator: Optional[str] = None,
    ) -> None:
        """Save a single translation into cache."""
        trans = translator or engine
        with self._lock:
            conn = self.get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO _translation_cache (source_text, target_text, translator, created_at) "
                "VALUES (?, ?, ?, ?)",
                [source_text, target_text, trans, datetime.now(timezone.utc)],
            )

    def get_translations_batch(self, texts: List[str]) -> Dict[str, str]:
        """Fetch cached translations in bulk."""
        if not texts:
            return {}
        with self._lock:
            conn = self.get_connection()
            placeholders = ", ".join(["?"] * len(texts))
            rows = conn.execute(
                f"SELECT source_text, target_text FROM _translation_cache WHERE source_text IN ({placeholders})",
                texts,
            ).fetchall()
            return {r[0]: r[1] for r in rows if r[1]}

    def save_translations_batch(
        self,
        translations: Dict[str, str],
        engine: str = "argos",
        translator: Optional[str] = None,
    ) -> None:
        """Save batch of translations into cache."""
        if not translations:
            return
        trans = translator or engine
        now = datetime.now(timezone.utc)
        entries = [
            {"source_text": src, "target_text": tgt, "translator": trans, "created_at": now}
            for src, tgt in translations.items()
        ]
        self.insert_batch_fast("_translation_cache", entries)

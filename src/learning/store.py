from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

import duckdb

from src.learning.schema import apply_migrations


class LearningGraphStore:
    """Own the DuckDB database used for the canonical learning graph."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._lock = RLock()

    def connection(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._connection is None:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = duckdb.connect(str(self._db_path))
                self._connection.execute("PRAGMA threads = 1")
            return self._connection

    def initialize(self) -> None:
        with self._lock:
            try:
                apply_migrations(self.connection())
            except ValueError as exc:
                if "newer than engine" in str(exc):
                    raise RuntimeError(
                        str(exc).replace("newer than engine", "newer than this engine")
                    ) from exc
                raise

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            connection = self.connection()
            connection.execute("BEGIN TRANSACTION")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def fetch_value(self, sql: str, params: Any = None) -> Any:
        with self._lock:
            result = self.connection().execute(sql, params)
            row = result.fetchone()
            return None if row is None else row[0]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

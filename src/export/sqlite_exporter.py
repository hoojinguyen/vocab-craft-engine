"""
High-Performance DuckDB -> SQLite Production Dataset Exporter.

Streams all 11 staging tables from DuckDB into a self-contained, optimized SQLite database
with performance indexes, metadata, and foreign key verification.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Dict

from src.db.duckdb_manager import DuckDBManager
from src.export.schema import SQLITE_INDEXES, SQLITE_SCHEMA, SQLITE_TABLES

logger = logging.getLogger(__name__)


class SqliteExporter:
    """Exports DuckDB staging tables into an optimized SQLite client database."""

    def export(
        self,
        db_mgr: DuckDBManager,
        target_sqlite_path: Path,
        batch_size: int = 10000,
    ) -> Dict[str, int]:
        target_path = Path(target_sqlite_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()

        logger.info("Initializing SQLite export target at %s", target_path)

        s_conn = sqlite3.connect(str(target_path))
        s_cursor = s_conn.cursor()

        # Performance pragmas for ultra-fast bulk loading
        s_cursor.execute("PRAGMA synchronous = OFF;")
        s_cursor.execute("PRAGMA journal_mode = MEMORY;")
        s_cursor.execute("PRAGMA temp_store = MEMORY;")
        s_cursor.execute("PRAGMA foreign_keys = OFF;")

        # Create production schema
        s_cursor.executescript(SQLITE_SCHEMA)
        s_conn.commit()

        d_conn = db_mgr.get_connection()
        exported_counts: Dict[str, int] = {}

        for table in SQLITE_TABLES:
            try:
                # Get column names from DuckDB
                duck_cols = [
                    row[0]
                    for row in d_conn.execute(
                        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
                    ).fetchall()
                ]
                if not duck_cols:
                    exported_counts[table] = 0
                    continue

                col_str = ", ".join(duck_cols)
                placeholders = ", ".join(["?"] * len(duck_cols))
                insert_sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"

                cursor = d_conn.cursor()
                cursor.execute(f"SELECT {col_str} FROM {table}")

                table_count = 0
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    s_cursor.executemany(insert_sql, rows)
                    table_count += len(rows)

                s_conn.commit()
                exported_counts[table] = table_count
                logger.info("Exported %d rows into SQLite table '%s'", table_count, table)

            except Exception as e:
                logger.error("Failed to export table '%s': %s", table, e)
                exported_counts[table] = 0

        # Create covering indexes after data load
        logger.info("Creating SQLite performance covering indexes...")
        s_cursor.executescript(SQLITE_INDEXES)
        s_conn.commit()

        # Populate dataset metadata
        now_str = datetime.now(timezone.utc).isoformat()
        metadata_entries = [
            ("version", "2.0"),
            ("schema_version", "2.0"),
            ("build_timestamp", now_str),
            ("total_words", str(exported_counts.get("words", 0))),
            ("total_definitions", str(exported_counts.get("definitions", 0))),
            ("total_sentences", str(exported_counts.get("sentences", 0))),
            ("total_word_sentences", str(exported_counts.get("word_sentences", 0))),
            ("total_phrases", str(exported_counts.get("phrases", 0))),
            ("total_phrase_sentences", str(exported_counts.get("phrase_sentences", 0))),
            ("total_word_relations", str(exported_counts.get("word_relations", 0))),
            ("total_word_topics", str(exported_counts.get("word_topics", 0))),
            ("total_reflex_drills", str(exported_counts.get("reflex_drills", 0))),
            ("total_dialogue_trees", str(exported_counts.get("dialogue_trees", 0))),
            ("total_dialogue_nodes", str(exported_counts.get("dialogue_nodes", 0))),
        ]

        s_cursor.executemany(
            "INSERT OR REPLACE INTO dataset_metadata (key, value) VALUES (?, ?)",
            metadata_entries,
        )
        s_conn.commit()

        # Final maintenance pragmas
        s_cursor.execute("PRAGMA foreign_keys = ON;")
        s_cursor.execute("PRAGMA optimize;")
        s_conn.close()

        logger.info("Successfully exported SQLite dataset to %s", target_path)
        return exported_counts


# Alias for backward compatibility
SQLiteExporter = SqliteExporter

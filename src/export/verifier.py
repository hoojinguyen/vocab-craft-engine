"""
Dataset Integrity Verifier for SQLite Export.

Performs schema verification, PRAGMA integrity checks, foreign key constraint checks,
JSON payload validation, and row count reporting.
"""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sqlite3
from typing import Dict, List

from src.export.schema import SQLITE_TABLES

logger = logging.getLogger(__name__)


@dataclass
class VerificationReport:
    is_valid: bool = True
    integrity_check_passed: bool = True
    foreign_key_violations: int = 0
    invalid_json_count: int = 0
    table_counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class DatasetVerifier:
    def verify(self, db_path: Path) -> VerificationReport:
        report = VerificationReport()
        path = Path(db_path)

        if not path.exists():
            report.is_valid = False
            report.errors.append(f"Database file not found at {path}")
            return report

        try:
            conn = sqlite3.connect(str(path))
            cursor = conn.cursor()

            # 1. SQLite PRAGMA integrity_check
            integrity_res = cursor.execute("PRAGMA integrity_check;").fetchall()
            if not integrity_res or integrity_res[0][0] != "ok":
                report.integrity_check_passed = False
                report.errors.append(f"Integrity check failed: {integrity_res}")

            # 2. SQLite PRAGMA foreign_key_check
            cursor.execute("PRAGMA foreign_keys = ON;")
            fk_violations = cursor.execute("PRAGMA foreign_key_check;").fetchall()
            report.foreign_key_violations = len(fk_violations)
            if fk_violations:
                report.errors.append(
                    f"Found {len(fk_violations)} foreign key violations in exported SQLite database"
                )

            # 3. Table counts
            for table in SQLITE_TABLES:
                try:
                    count_row = cursor.execute(f"SELECT count(*) FROM {table}").fetchone()
                    report.table_counts[table] = count_row[0] if count_row else 0
                except Exception as e:
                    report.table_counts[table] = 0
                    report.errors.append(f"Table '{table}' query failed: {e}")

            # 4. Validate reflex_drills JSON payloads
            try:
                drill_rows = cursor.execute(
                    "SELECT id, distractors_json FROM reflex_drills WHERE distractors_json IS NOT NULL"
                ).fetchall()
                for drill_id, dist_json in drill_rows:
                    try:
                        parsed = json.loads(dist_json)
                        if not isinstance(parsed, list):
                            report.invalid_json_count += 1
                    except Exception:
                        report.invalid_json_count += 1

                if report.invalid_json_count > 0:
                    report.errors.append(
                        f"Found {report.invalid_json_count} invalid distractors_json in reflex_drills"
                    )
            except Exception as e:
                logger.warning("Could not check reflex_drills JSON: %s", e)

            # 5. Validate dataset_metadata
            try:
                meta_row = cursor.execute(
                    "SELECT value FROM dataset_metadata WHERE key = 'version'"
                ).fetchone()
                if not meta_row:
                    report.errors.append("Missing 'version' key in dataset_metadata table")
            except Exception as e:
                report.errors.append(f"dataset_metadata check failed: {e}")

            conn.close()

        except Exception as e:
            report.is_valid = False
            report.errors.append(f"Fatal verification error: {e}")

        report.is_valid = (
            report.integrity_check_passed
            and report.foreign_key_violations == 0
            and report.invalid_json_count == 0
            and len(report.errors) == 0
        )

        return report

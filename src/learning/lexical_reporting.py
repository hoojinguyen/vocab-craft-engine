"""Deterministic, internal reporting artifacts for lexical remediation runs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.models import canonical_json
from src.learning.store import LearningGraphStore


@dataclass(frozen=True)
class QuarantineExportResult:
    database_path: Path
    checksum_path: Path


class LexicalRunReporter:
    """Write stable reports only after a run accounts for every source input."""

    def __init__(self, store: LearningGraphStore) -> None:
        self.store = store

    def write_input_manifest(self, snapshot_id: str, output_dir: Path) -> Path:
        """Persist the complete ordered input inventory for one source snapshot."""
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT input_id, input_key, raw_record_id, source_word_id,
                   source_definition_id, lemma, pos, frequency_rank,
                   source_definition_sha256
            FROM lexical_definition_inputs
            WHERE snapshot_id = ?
            ORDER BY frequency_rank, source_word_id, source_definition_id, input_key
            """,
                [snapshot_id],
            )
            .fetchall()
        )
        source_evidence_inventory = self._source_evidence_inventory(snapshot_id)
        document = {
            "input_total": len(rows),
            "normalized_source_evidence_count": source_evidence_inventory[
                "normalized_source_evidence_count"
            ],
            "normalized_word_evidence_link_count": source_evidence_inventory[
                "normalized_word_evidence_link_count"
            ],
            "source_definition_count": len(rows),
            "source_linked_example_count": source_evidence_inventory[
                "normalized_word_evidence_link_count"
            ],
            "inputs": [
                {
                    "input_id": str(row[0]),
                    "input_key": str(row[1]),
                    "raw_record_id": str(row[2]),
                    "source_word_id": int(row[3]),
                    "source_definition_id": int(row[4]),
                    "lemma": str(row[5]),
                    "pos": str(row[6]),
                    "frequency_rank": int(row[7]),
                    "source_definition_sha256": str(row[8]),
                }
                for row in rows
            ],
            "snapshot_id": snapshot_id,
        }
        return self._write_json(Path(output_dir) / "input_manifest.json", document)

    def write_remediation_report(
        self, validation_run_id: str, output_dir: Path
    ) -> Path:
        snapshot_id = self._snapshot_id(validation_run_id)
        input_total = int(
            self.store.fetch_value(
                "SELECT count(*) FROM lexical_definition_inputs WHERE snapshot_id = ?",
                [snapshot_id],
            )
        )
        disposition_rows = (
            self.store.connection()
            .execute(
                """
            SELECT input.input_id, input.input_key, input.source_word_id,
                   input.source_definition_id, input.lemma, input.pos,
                   input.frequency_rank, source.asset_id, disposition.state,
                   disposition.failure_codes_json
            FROM lexical_definition_inputs AS input
            JOIN source_snapshots AS snapshot ON snapshot.snapshot_id = input.snapshot_id
            JOIN source_assets AS source ON source.asset_id = snapshot.asset_id
            LEFT JOIN lexical_input_dispositions AS disposition
              ON disposition.input_id = input.input_id
             AND disposition.validation_run_id = ?
            WHERE input.snapshot_id = ?
            ORDER BY input.frequency_rank, input.source_word_id,
                     input.source_definition_id, input.input_key
            """,
                [validation_run_id, snapshot_id],
            )
            .fetchall()
        )
        missing = [str(row[0]) for row in disposition_rows if row[8] is None]
        if missing:
            raise ValueError(
                "remediation run has missing dispositions for "
                f"{len(missing)} lexical inputs"
            )
        if len(disposition_rows) != input_total:
            raise ValueError("remediation input total does not match its snapshot")

        counts_by_state = self._count(row[8] for row in disposition_rows)
        if sum(counts_by_state.values()) != input_total:
            raise ValueError("remediation disposition counts do not reconcile")
        counts_by_rank_band = self._count(
            self._rank_band(int(row[6])) for row in disposition_rows
        )
        counts_by_pos = self._count(row[5] for row in disposition_rows)
        counts_by_source = self._count(row[7] for row in disposition_rows)
        gate_rows = (
            self.store.connection()
            .execute(
                """
            SELECT gate_code, count(*)
            FROM candidate_gate_results
            WHERE validation_run_id = ? AND NOT passed
            GROUP BY gate_code ORDER BY gate_code
            """,
                [validation_run_id],
            )
            .fetchall()
        )
        retry_rows = (
            self.store.connection()
            .execute(
                """
            SELECT outcome, count(*)
            FROM lexical_remediation_attempts
            WHERE validation_run_id = ? AND attempt_number > 1
            GROUP BY outcome ORDER BY outcome
            """,
                [validation_run_id],
            )
            .fetchall()
        )
        conflict_rows = (
            self.store.connection()
            .execute(
                """
            SELECT canonical_key, count(*)
            FROM lexical_input_canonical_map AS mapping
            JOIN lexical_definition_inputs AS input ON input.input_id = mapping.input_id
            WHERE input.snapshot_id = ?
            GROUP BY canonical_key HAVING count(*) > 1
            ORDER BY canonical_key
            """,
                [snapshot_id],
            )
            .fetchall()
        )
        document = {
            "counts_by_canonical_conflict_type": (
                {"duplicate_input": len(conflict_rows)} if conflict_rows else {}
            ),
            "counts_by_gate_code": {str(code): int(count) for code, count in gate_rows},
            "counts_by_pos": counts_by_pos,
            "counts_by_rank_band": counts_by_rank_band,
            "counts_by_retry_outcome": {
                str(outcome): int(count) for outcome, count in retry_rows
            },
            "counts_by_source": counts_by_source,
            "counts_by_state": counts_by_state,
            "input_total": input_total,
            "samples": self._samples(validation_run_id, disposition_rows),
            "snapshot_id": snapshot_id,
            "source_evidence_inventory": self._source_evidence_inventory(snapshot_id),
            "validation_run_id": validation_run_id,
        }
        return self._write_json(Path(output_dir) / "remediation_report.json", document)

    def _snapshot_id(self, validation_run_id: str) -> str:
        snapshot_id = self.store.fetch_value(
            "SELECT snapshot_id FROM validation_runs WHERE validation_run_id = ?",
            [validation_run_id],
        )
        if snapshot_id is None:
            raise ValueError(f"validation run {validation_run_id!r} does not exist")
        return str(snapshot_id)

    def _source_evidence_inventory(self, snapshot_id: str) -> dict[str, int]:
        """Counts are source facts, not a per-definition evidence expansion."""
        evidence_count = self.store.fetch_value(
            """
            SELECT count(*) FROM lexical_source_evidence
            WHERE snapshot_id = ? AND evidence_role = 'example'
            """,
            [snapshot_id],
        )
        link_count = self.store.fetch_value(
            """
            SELECT count(*) FROM lexical_word_evidence_links
            WHERE snapshot_id = ?
            """,
            [snapshot_id],
        )
        return {
            "normalized_source_evidence_count": int(evidence_count or 0),
            "normalized_word_evidence_link_count": int(link_count or 0),
        }

    def _samples(
        self, validation_run_id: str, disposition_rows: list[tuple[Any, ...]]
    ) -> dict[str, list[dict[str, Any]]]:
        samples: dict[str, list[dict[str, Any]]] = {}
        for row in disposition_rows:
            state = str(row[8])
            evidence_rows = (
                self.store.connection()
                .execute(
                    """
                SELECT evidence_id, source_row_id
                FROM lexical_evidence_items
                WHERE input_id = ?
                ORDER BY evidence_role, source_row_id, evidence_id
                """,
                    [row[0]],
                )
                .fetchall()
            )
            samples.setdefault(state, []).append(
                {
                    "failure_codes": json.loads(str(row[9])),
                    "input_id": str(row[0]),
                    "input_key": str(row[1]),
                    "evidence_ids": [
                        str(evidence_id) for evidence_id, _ in evidence_rows
                    ],
                    "source_row_ids": [
                        int(source_row_id) for _, source_row_id in evidence_rows
                    ],
                }
            )
        return {state: values[:10] for state, values in sorted(samples.items())}

    @staticmethod
    def _rank_band(rank: int) -> str:
        if rank <= 500:
            return "A1"
        if rank <= 1500:
            return "A2"
        return "B1"

    @staticmethod
    def _count(values: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json(document) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        return path


class QuarantineExporter:
    """Export an internal, evidence-complete SQLite quarantine work queue."""

    def __init__(self, store: LearningGraphStore) -> None:
        self.store = store

    def export(
        self, validation_run_id: str, output_dir: Path
    ) -> QuarantineExportResult:
        destination = Path(output_dir) / "quarantine_v1.db"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".db", dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            self._write_database(validation_run_id, temporary_path)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        checksum_path = destination.with_suffix(destination.suffix + ".sha256")
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=checksum_path.parent, delete=False
        ) as temporary:
            temporary.write(f"{checksum}  {destination.name}\n")
            temporary_checksum = Path(temporary.name)
        os.replace(temporary_checksum, checksum_path)
        return QuarantineExportResult(destination, checksum_path)

    def _write_database(self, validation_run_id: str, path: Path) -> None:
        source = self.store.connection()
        stale_cases = source.execute(
            """
            SELECT disposition.input_id
            FROM lexical_input_dispositions AS disposition
            LEFT JOIN lexical_quarantine_cases AS quarantine
              ON quarantine.input_id = disposition.input_id
            WHERE disposition.validation_run_id = ?
              AND disposition.state = 'quarantined'
              AND (
                  quarantine.case_id IS NULL
                  OR quarantine.latest_validation_run_id <> ?
              )
            ORDER BY disposition.input_id
            LIMIT 1
            """,
            [validation_run_id, validation_run_id],
        ).fetchone()
        if stale_cases is not None:
            raise ValueError(
                "validation run is not current for quarantine export: "
                f"{stale_cases[0]}"
            )
        cases = source.execute(
            """
            SELECT quarantine.case_id, quarantine.input_id, quarantine.latest_validation_run_id,
                   quarantine.status, quarantine.retry_count, quarantine.failure_codes_json,
                   quarantine.alternatives_json, quarantine.updated_at
            FROM lexical_quarantine_cases AS quarantine
            JOIN lexical_input_dispositions AS disposition
              ON disposition.input_id = quarantine.input_id
            WHERE disposition.validation_run_id = ? AND disposition.state = 'quarantined'
            ORDER BY quarantine.input_id
            """,
            [validation_run_id],
        ).fetchall()
        input_ids = [str(row[1]) for row in cases]
        with sqlite3.connect(path) as destination:
            destination.execute("PRAGMA foreign_keys = ON")
            destination.executescript("""
                CREATE TABLE quarantine_cases (
                    case_id TEXT PRIMARY KEY,
                    input_id TEXT NOT NULL UNIQUE,
                    latest_validation_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    failure_codes_json TEXT NOT NULL,
                    alternatives_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE remediation_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES quarantine_cases(case_id),
                    validation_run_id TEXT NOT NULL,
                    input_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    selection_json TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    failure_codes_json TEXT NOT NULL,
                    rationale_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE evidence_items (
                    evidence_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES quarantine_cases(case_id),
                    input_id TEXT NOT NULL,
                    evidence_role TEXT NOT NULL,
                    source_row_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE ranked_alternatives (
                    validation_run_id TEXT NOT NULL,
                    input_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id),
                    evidence_role TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    selected INTEGER NOT NULL,
                    eligible INTEGER NOT NULL,
                    reason_json TEXT NOT NULL,
                    PRIMARY KEY(validation_run_id, input_id, evidence_id)
                );
            """)
            destination.executemany(
                "INSERT INTO quarantine_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [tuple(str(value) for value in row) for row in cases],
            )
            if input_ids:
                placeholders = ", ".join("?" for _ in input_ids)
                case_by_input = {str(row[1]): str(row[0]) for row in cases}
                attempts = source.execute(
                    f"""
                    SELECT attempt_id, validation_run_id, input_id, attempt_number,
                           selection_json, outcome, failure_codes_json, rationale_json, created_at
                    FROM lexical_remediation_attempts
                    WHERE validation_run_id = ? AND input_id IN ({placeholders})
                    ORDER BY input_id, attempt_number
                    """,
                    [validation_run_id, *input_ids],
                ).fetchall()
                destination.executemany(
                    "INSERT INTO remediation_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            str(row[0]),
                            case_by_input[str(row[2])],
                            str(row[1]),
                            str(row[2]),
                            int(row[3]),
                            str(row[4]),
                            str(row[5]),
                            str(row[6]),
                            str(row[7]),
                            str(row[8]),
                        )
                        for row in attempts
                    ],
                )
                evidence = source.execute(
                    f"""
                    SELECT evidence_id, input_id, evidence_role, source_row_id,
                           source_name, value_json
                    FROM lexical_evidence_items
                    WHERE input_id IN ({placeholders})
                    ORDER BY input_id, evidence_role, source_row_id, evidence_id
                    """,
                    input_ids,
                ).fetchall()
                destination.executemany(
                    "INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            str(row[0]),
                            case_by_input[str(row[1])],
                            str(row[1]),
                            str(row[2]),
                            int(row[3]),
                            str(row[4]),
                            str(row[5]),
                        )
                        for row in evidence
                    ],
                )
                rankings = source.execute(
                    f"""
                    SELECT validation_run_id, input_id, evidence_id, evidence_role,
                           rank, selected, eligible, reason_json
                    FROM lexical_evidence_rankings
                    WHERE validation_run_id = ? AND input_id IN ({placeholders})
                    ORDER BY input_id, evidence_role, rank, evidence_id
                    """,
                    [validation_run_id, *input_ids],
                ).fetchall()
                destination.executemany(
                    "INSERT INTO ranked_alternatives VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            str(row[0]),
                            str(row[1]),
                            str(row[2]),
                            str(row[3]),
                            int(row[4]),
                            int(bool(row[5])),
                            int(bool(row[6])),
                            str(row[7]),
                        )
                        for row in rankings
                    ],
                )
            destination.commit()
            if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("quarantine export SQLite integrity check failed")
            if destination.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("quarantine export SQLite foreign key check failed")

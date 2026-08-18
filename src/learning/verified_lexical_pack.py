"""Compose the complete, reviewed lexical release for backend consumption.

Unlike :mod:`src.learning.lexical_pack`, this module has no CEFR slice or
per-source quota.  It is intentionally fail-closed: a release exists only
after every imported definition in one remediation run has an auditable final
outcome.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from src.learning.quality import QualityGate
from src.learning.store import LearningGraphStore


@dataclass(frozen=True)
class VerifiedLexicalPack:
    """A fully reconciled set of approved canonical senses and lineage."""

    version: str
    validation_run_id: str
    policy_version: str
    senses: tuple[dict[str, object], ...]
    examples: tuple[dict[str, object], ...]
    provenance: tuple[dict[str, object], ...]
    source_attributions: tuple[dict[str, object], ...]
    source_snapshots: tuple[dict[str, object], ...]
    reconciliation: dict[str, int]


@dataclass(frozen=True)
class _InputOutcome:
    input_id: str
    raw_record_id: str
    source_word_id: int
    source_definition_id: int
    disposition: str
    disposition_candidate_id: str | None
    canonical_key: str | None
    mapped_candidate_id: str | None
    candidate_state: str | None
    candidate_payload_json: str | None
    candidate_evidence_json: str | None


class VerifiedLexicalPackComposer:
    """Turn one completely reviewed remediation run into an immutable pack."""

    def __init__(
        self, store: LearningGraphStore, quality_gate: QualityGate | None = None
    ) -> None:
        self.store = store
        self.quality_gate = quality_gate or QualityGate()

    def compose(self, validation_run_id: str, version: str) -> VerifiedLexicalPack:
        snapshot_id, policy_version = self._run_identity(validation_run_id)
        outcomes = self._input_outcomes(validation_run_id, snapshot_id)
        if not outcomes:
            raise ValueError("release validation run has no lexical inputs")
        self._require_complete_reconciliation(validation_run_id, snapshot_id, outcomes)
        self._require_no_open_quarantine(snapshot_id)

        approved_by_key: dict[str, list[_InputOutcome]] = defaultdict(list)
        disposition_counts: Counter[str] = Counter()
        for outcome in outcomes:
            disposition_counts[outcome.disposition] += 1
            if outcome.disposition == "quarantined":
                raise ValueError("release validation run still has quarantined inputs")
            if outcome.disposition == "rejected":
                self._require_rejected_input(outcome)
                continue
            if outcome.disposition != "validated":
                raise ValueError(
                    f"unsupported lexical disposition for release: {outcome.disposition}"
                )
            self._require_approved_input(validation_run_id, outcome)
            assert outcome.canonical_key is not None
            approved_by_key[outcome.canonical_key].append(outcome)

        if not approved_by_key:
            raise ValueError("release has no approved lexical senses")

        senses: list[dict[str, object]] = []
        examples: list[dict[str, object]] = []
        provenance: list[dict[str, object]] = []
        for canonical_key in sorted(approved_by_key):
            grouped_outcomes = approved_by_key[canonical_key]
            sense_id, payload, source_candidate_id = self._latest_approved_sense(
                canonical_key
            )
            grouped_candidate_ids = {
                str(outcome.disposition_candidate_id) for outcome in grouped_outcomes
            }
            if source_candidate_id not in grouped_candidate_ids:
                raise ValueError(
                    "latest approved revision is not sourced from this validation run"
                )
            if str(payload.get("stable_key")) != canonical_key:
                raise ValueError(
                    "approved revision stable key does not match lexical map"
                )
            quality = self.quality_gate.validate_payload("sense", payload, sense_id)
            if not quality.passed:
                raise ValueError(
                    "approved lexical revision failed structural quality gates"
                )
            sense = self._sense_row(sense_id, canonical_key, payload)
            senses.append(sense)
            examples.extend(self._examples(sense_id, payload))
            provenance.extend(
                self._provenance_rows(sense_id, snapshot_id, grouped_outcomes)
            )

        senses.sort(
            key=lambda row: (
                int(row["frequency_rank"]),
                str(row["lemma"]),
                str(row["pos"]),
                str(row["stable_key"]),
            )
        )
        examples.sort(key=lambda row: (str(row["sense_id"]), int(row["rank"])))
        provenance.sort(
            key=lambda row: (
                str(row["sense_id"]),
                str(row["raw_record_id"]),
                int(row["source_definition_id"]),
            )
        )
        reconciliation = {
            "input_total": len(outcomes),
            "validated_input_count": disposition_counts["validated"],
            "quarantined_input_count": disposition_counts["quarantined"],
            "rejected_input_count": disposition_counts["rejected"],
            "approved_candidate_count": sum(
                len(rows) for rows in approved_by_key.values()
            ),
            "approved_sense_count": len(senses),
            "approved_provenance_count": len(provenance),
        }
        if (
            reconciliation["validated_input_count"]
            + reconciliation["quarantined_input_count"]
            + reconciliation["rejected_input_count"]
            != reconciliation["input_total"]
        ):
            raise ValueError("release disposition counts do not reconcile")
        return VerifiedLexicalPack(
            version=version,
            validation_run_id=validation_run_id,
            policy_version=policy_version,
            senses=tuple(senses),
            examples=tuple(examples),
            provenance=tuple(provenance),
            source_attributions=self._source_attributions(snapshot_id),
            source_snapshots=self._source_snapshots(snapshot_id),
            reconciliation=reconciliation,
        )

    def _run_identity(self, validation_run_id: str) -> tuple[str, str]:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT snapshot_id, policy_version
            FROM validation_runs
            WHERE validation_run_id = ?
            """,
                [validation_run_id],
            )
            .fetchone()
        )
        if row is None:
            raise ValueError(f"validation run does not exist: {validation_run_id!r}")
        return str(row[0]), str(row[1])

    def _input_outcomes(
        self, validation_run_id: str, snapshot_id: str
    ) -> list[_InputOutcome]:
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT input.input_id, input.raw_record_id, input.source_word_id,
                   input.source_definition_id, disposition.state,
                   disposition.candidate_id, mapping.canonical_key,
                   mapping.candidate_id, candidate.state,
                   candidate.normalized_payload_json, candidate.evidence_json
            FROM lexical_definition_inputs AS input
            LEFT JOIN lexical_input_dispositions AS disposition
              ON disposition.input_id = input.input_id
             AND disposition.validation_run_id = ?
            LEFT JOIN lexical_input_canonical_map AS mapping
              ON mapping.input_id = input.input_id
            LEFT JOIN content_candidates AS candidate
              ON candidate.candidate_id = disposition.candidate_id
            WHERE input.snapshot_id = ?
            ORDER BY input.frequency_rank, input.source_word_id,
                     input.source_definition_id, input.input_key
            """,
                [validation_run_id, snapshot_id],
            )
            .fetchall()
        )
        return [
            _InputOutcome(
                input_id=str(row[0]),
                raw_record_id=str(row[1]),
                source_word_id=int(row[2]),
                source_definition_id=int(row[3]),
                disposition="" if row[4] is None else str(row[4]),
                disposition_candidate_id=None if row[5] is None else str(row[5]),
                canonical_key=None if row[6] is None else str(row[6]),
                mapped_candidate_id=None if row[7] is None else str(row[7]),
                candidate_state=None if row[8] is None else str(row[8]),
                candidate_payload_json=None if row[9] is None else str(row[9]),
                candidate_evidence_json=None if row[10] is None else str(row[10]),
            )
            for row in rows
        ]

    def _require_complete_reconciliation(
        self,
        validation_run_id: str,
        snapshot_id: str,
        outcomes: list[_InputOutcome],
    ) -> None:
        missing = [outcome.input_id for outcome in outcomes if not outcome.disposition]
        if missing:
            raise ValueError(
                "release validation run has missing dispositions for lexical inputs"
            )
        total_dispositions = int(
            self.store.fetch_value(
                "SELECT count(*) FROM lexical_input_dispositions WHERE validation_run_id = ?",
                [validation_run_id],
            )
        )
        if total_dispositions != len(outcomes):
            raise ValueError(
                "release reconciliation total does not match its validation snapshot"
            )
        snapshot_dispositions = int(
            self.store.fetch_value(
                """
                SELECT count(*)
                FROM lexical_input_dispositions AS disposition
                JOIN lexical_definition_inputs AS input ON input.input_id = disposition.input_id
                WHERE disposition.validation_run_id = ? AND input.snapshot_id = ?
                """,
                [validation_run_id, snapshot_id],
            )
        )
        if snapshot_dispositions != len(outcomes):
            raise ValueError("release reconciliation has duplicate or foreign inputs")

    def _require_no_open_quarantine(self, snapshot_id: str) -> None:
        open_case = (
            self.store.connection()
            .execute(
                """
            SELECT quarantine.input_id
            FROM lexical_quarantine_cases AS quarantine
            JOIN lexical_definition_inputs AS input ON input.input_id = quarantine.input_id
            WHERE input.snapshot_id = ? AND quarantine.status = 'open'
            ORDER BY quarantine.input_id
            LIMIT 1
            """,
                [snapshot_id],
            )
            .fetchone()
        )
        if open_case is not None:
            raise ValueError(f"release has open quarantine case: {open_case[0]}")

    @staticmethod
    def _require_mapping(outcome: _InputOutcome) -> None:
        if not outcome.canonical_key or not outcome.mapped_candidate_id:
            raise ValueError("released lexical input is missing a canonical mapping")
        if outcome.disposition_candidate_id != outcome.mapped_candidate_id:
            raise ValueError(
                "lexical disposition and canonical map disagree on candidate"
            )

    def _require_approved_input(
        self, validation_run_id: str, outcome: _InputOutcome
    ) -> None:
        self._require_mapping(outcome)
        if outcome.candidate_state != "approved":
            raise ValueError(
                "validated lexical input does not have an approved candidate"
            )
        assert outcome.disposition_candidate_id is not None
        if not self._candidate_gates_passed(
            validation_run_id, outcome.disposition_candidate_id
        ):
            raise ValueError(
                "approved lexical candidate is missing a passed gate result"
            )
        approved_revisions = int(
            self.store.fetch_value(
                """
                SELECT count(*) FROM content_revisions
                WHERE source_candidate_id = ? AND review_state = 'approved'
                """,
                [outcome.disposition_candidate_id],
            )
        )
        if approved_revisions == 0:
            raise ValueError("approved lexical candidate has no approved revision")
        if outcome.candidate_payload_json is None:
            raise ValueError("approved lexical candidate is missing a payload")
        payload = json.loads(outcome.candidate_payload_json)
        if (
            not isinstance(payload, dict)
            or payload.get("stable_key") != outcome.canonical_key
        ):
            raise ValueError(
                "candidate payload does not match its canonical lexical map"
            )

    def _require_rejected_input(self, outcome: _InputOutcome) -> None:
        self._require_mapping(outcome)
        if outcome.candidate_state != "rejected":
            raise ValueError("excluded lexical input is not explicitly rejected")

    def _candidate_gates_passed(
        self, validation_run_id: str, candidate_id: str
    ) -> bool:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT count(*) AS result_count,
                   coalesce(sum(CASE WHEN NOT passed THEN 1 ELSE 0 END), 0) AS failed_count
            FROM candidate_gate_results
            WHERE validation_run_id = ? AND candidate_id = ?
            """,
                [validation_run_id, candidate_id],
            )
            .fetchone()
        )
        return row is not None and int(row[0]) > 0 and int(row[1]) == 0

    def _latest_approved_sense(
        self, canonical_key: str
    ) -> tuple[str, dict[str, Any], str]:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT revision.revision_id, revision.payload_json, revision.source_candidate_id
            FROM content_revisions AS revision
            JOIN canonical_content AS content ON content.content_id = revision.content_id
            WHERE content.stable_key = ?
              AND content.content_type = 'sense'
              AND revision.review_state = 'approved'
            ORDER BY revision.revision_number DESC, revision.revision_id DESC
            LIMIT 1
            """,
                [canonical_key],
            )
            .fetchone()
        )
        if row is None:
            raise ValueError(
                "approved lexical canonical content has no approved revision"
            )
        payload = json.loads(str(row[1]))
        if not isinstance(payload, dict):
            raise TypeError("approved lexical revision payload must be an object")
        return str(row[0]), payload, str(row[2])

    @staticmethod
    def _sense_row(
        sense_id: str, canonical_key: str, payload: dict[str, Any]
    ) -> dict[str, object]:
        return {
            "sense_id": sense_id,
            "stable_key": canonical_key,
            "lemma": str(payload["lemma"]),
            "pos": str(payload["pos"]),
            "definition_en": str(payload["definition_en"]),
            "definition_vi": str(payload["definition_vi"]),
            "ipa_uk": payload.get("ipa_uk"),
            "ipa_us": payload.get("ipa_us"),
            "frequency_rank": int(payload["frequency_rank"]),
            "cefr_level": str(payload["cefr_level"]),
        }

    @staticmethod
    def _examples(sense_id: str, payload: dict[str, Any]) -> list[dict[str, object]]:
        values = payload.get("examples", [])
        if not isinstance(values, list):
            raise TypeError("approved lexical revision examples must be a list")
        rows: list[dict[str, object]] = []
        for rank, example in enumerate(values, start=1):
            if not isinstance(example, dict):
                raise TypeError("approved lexical revision has an invalid example")
            rows.append(
                {
                    "sense_id": sense_id,
                    "rank": rank,
                    "text_en": str(example["text_en"]),
                    "text_vi": str(example["text_vi"]),
                    "source": str(example["source"]),
                }
            )
        return rows

    @staticmethod
    def _provenance_rows(
        sense_id: str, snapshot_id: str, outcomes: list[_InputOutcome]
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for outcome in outcomes:
            if outcome.candidate_evidence_json is None:
                raise ValueError(
                    "approved lexical candidate is missing source evidence"
                )
            evidence = json.loads(outcome.candidate_evidence_json)
            rows.append(
                {
                    "sense_id": sense_id,
                    "snapshot_id": snapshot_id,
                    "raw_record_id": outcome.raw_record_id,
                    "source_word_id": outcome.source_word_id,
                    "source_definition_id": outcome.source_definition_id,
                    "evidence": evidence,
                }
            )
        return rows

    def _source_attributions(self, snapshot_id: str) -> tuple[dict[str, object], ...]:
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT source.asset_id, source.title, source.license_id, source.license_url,
                   source.attribution, source.sha256
            FROM source_snapshots AS snapshot
            JOIN source_assets AS source ON source.asset_id = snapshot.asset_id
            WHERE snapshot.snapshot_id = ?
            ORDER BY source.asset_id
            """,
                [snapshot_id],
            )
            .fetchall()
        )
        return tuple(
            {
                "asset_id": str(row[0]),
                "title": str(row[1]),
                "license_id": str(row[2]),
                "license_url": str(row[3]),
                "attribution": str(row[4]),
                "sha256": str(row[5]),
            }
            for row in rows
        )

    def _source_snapshots(self, snapshot_id: str) -> tuple[dict[str, object], ...]:
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT snapshot_id, asset_id, file_sha256
            FROM source_snapshots
            WHERE snapshot_id = ?
            ORDER BY snapshot_id
            """,
                [snapshot_id],
            )
            .fetchall()
        )
        return tuple(
            {
                "snapshot_id": str(row[0]),
                "asset_id": str(row[1]),
                "file_sha256": str(row[2]),
            }
            for row in rows
        )

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.learning.models import CandidateState, canonical_json
from src.learning.quality import GateReport, QualityGate, cefr_for_rank
from src.learning.repository import ContentRepository
from src.learning.store import LearningGraphStore

LEXICAL_POLICY_VERSION = "lexical-v1"
LEXICAL_POLICY_SELECTION = {
    "content_type": "sense",
    "record_type": "sqlite_lexical_bundle",
}
_SUCCESS_GATE_CODE = "sense.complete"


@dataclass(frozen=True)
class LexicalAuditReport:
    validation_run_id: str
    candidate_state_counts: dict[str, int]
    gate_code_counts: dict[str, int]


class LexicalAuditService:
    """Project immutable lexical bundles into audited sense candidates."""

    def __init__(
        self,
        store: LearningGraphStore,
        quality_gate: QualityGate | None = None,
        repository: ContentRepository | None = None,
    ) -> None:
        self.store = store
        self.quality_gate = quality_gate or QualityGate()
        self.repository = repository or ContentRepository(store)

    def audit(self, snapshot_id: str) -> LexicalAuditReport:
        source_asset_id = self._source_asset_for_snapshot(snapshot_id)
        validation_run_id = str(uuid4())
        self._create_validation_run(validation_run_id, snapshot_id)

        for raw_record_id, payload_json in self._raw_bundles(source_asset_id):
            self._audit_bundle(
                validation_run_id,
                raw_record_id,
                source_asset_id,
                self._decode_bundle(payload_json),
            )

        self._complete_validation_run(validation_run_id)
        return self._report(validation_run_id)

    def _source_asset_for_snapshot(self, snapshot_id: str) -> str:
        source_asset_id = self.store.fetch_value(
            "SELECT asset_id FROM source_snapshots WHERE snapshot_id = ?", [snapshot_id]
        )
        if source_asset_id is None:
            raise ValueError(f"source snapshot does not exist: {snapshot_id!r}")
        return str(source_asset_id)

    def _create_validation_run(self, validation_run_id: str, snapshot_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO validation_runs (
                    validation_run_id, snapshot_id, policy_version, selection_json
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    validation_run_id,
                    snapshot_id,
                    LEXICAL_POLICY_VERSION,
                    canonical_json(LEXICAL_POLICY_SELECTION),
                ],
            )

    def _raw_bundles(self, source_asset_id: str) -> list[tuple[str, str]]:
        rows = (
            self.store.connection()
            .execute(
                """
                SELECT raw_record_id, payload_json
                FROM raw_reference_records
                WHERE asset_id = ? AND record_type = ?
                ORDER BY external_key, raw_record_id
                """,
                [source_asset_id, LEXICAL_POLICY_SELECTION["record_type"]],
            )
            .fetchall()
        )
        return [
            (str(raw_record_id), str(payload_json))
            for raw_record_id, payload_json in rows
        ]

    def _audit_bundle(
        self,
        validation_run_id: str,
        raw_record_id: str,
        source_asset_id: str,
        bundle: dict[str, Any],
    ) -> None:
        word = bundle.get("word")
        definitions = bundle.get("definitions")
        if not isinstance(word, dict) or not isinstance(definitions, list):
            return
        examples = bundle.get("examples")
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            payload = self._sense_payload(word, definition, examples, source_asset_id)
            candidate_id = self.repository.create_candidate(
                raw_record_id,
                "sense",
                payload,
                {"source_asset_id": source_asset_id, "raw_record_id": raw_record_id},
                1.0,
            )
            report = self.quality_gate.validate_payload("sense", payload, candidate_id)
            self._persist_gate_results(validation_run_id, candidate_id, report)
            self._transition_candidate(candidate_id, report)

    @staticmethod
    def _decode_bundle(payload_json: str) -> dict[str, Any]:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise TypeError("raw lexical bundle payload must be an object")
        return payload

    @staticmethod
    def _sense_payload(
        word: dict[str, Any],
        definition: dict[str, Any],
        examples: object,
        source_asset_id: str,
    ) -> dict[str, Any]:
        lemma = LexicalAuditService._normalized_identifier(word.get("lemma"))
        pos = LexicalAuditService._normalized_identifier(word.get("pos"))
        definition_en = definition.get("definition_en")
        definition_hash = hashlib.sha256(
            str(definition_en or "").encode("utf-8")
        ).hexdigest()
        ipa_uk = word.get("ipa_uk")
        ipa_us = word.get("ipa_us")
        has_ipa = bool(ipa_uk or ipa_us)
        source = word.get("source")
        return {
            "stable_key": f"sense.{lemma}.{pos}.{definition_hash[:12]}",
            "lemma": lemma,
            "pos": pos,
            "frequency_rank": word.get("frequency_rank"),
            "cefr_level": cefr_for_rank(word.get("frequency_rank")),
            "cefr_method": "frequency_rank_v1",
            "definition_en": definition_en,
            "definition_vi": definition.get("definition_vi"),
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "ipa_source": source if has_ipa else None,
            "ipa_confidence": 0.8 if source == "kaikki" and has_ipa else 0.0,
            "examples": examples if isinstance(examples, list) else [],
            "source_asset_id": source_asset_id,
        }

    @staticmethod
    def _normalized_identifier(value: object) -> str:
        return value.strip().casefold() if isinstance(value, str) else ""

    def _persist_gate_results(
        self, validation_run_id: str, candidate_id: str, report: GateReport
    ) -> None:
        outcomes = [
            (
                failure.code,
                False,
                failure.message,
                canonical_json({"revision_id": failure.revision_id}),
            )
            for failure in report.failures
        ]
        if not outcomes:
            outcomes = [
                (
                    _SUCCESS_GATE_CODE,
                    True,
                    "All lexical quality gates passed",
                    canonical_json({}),
                )
            ]
        with self.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO candidate_gate_results (
                    validation_run_id, candidate_id, gate_code, passed, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        validation_run_id,
                        candidate_id,
                        gate_code,
                        passed,
                        message,
                        details_json,
                    )
                    for gate_code, passed, message, details_json in outcomes
                ],
            )

    def _transition_candidate(self, candidate_id: str, report: GateReport) -> None:
        state = self.store.fetch_value(
            "SELECT state FROM content_candidates WHERE candidate_id = ?",
            [candidate_id],
        )
        if state is None:
            raise ValueError(f"candidate {candidate_id!r} does not exist")
        if report.passed:
            if state == CandidateState.CANDIDATE.value:
                self.repository.mark_candidate_validated(candidate_id)
            return
        if state in {CandidateState.CANDIDATE.value, CandidateState.VALIDATED.value}:
            self.repository.review_candidate(
                candidate_id,
                CandidateState.QUARANTINED.value,
                "validator:lexical-v1",
                ",".join(failure.code for failure in report.failures),
            )

    def _complete_validation_run(self, validation_run_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE validation_runs
                SET completed_at = current_timestamp
                WHERE validation_run_id = ?
                """,
                [validation_run_id],
            )

    def _report(self, validation_run_id: str) -> LexicalAuditReport:
        candidates = self.repository.candidates_for_validation_run(validation_run_id)
        state_counts = Counter(str(candidate["state"]) for candidate in candidates)
        gate_rows = (
            self.store.connection()
            .execute(
                """
                SELECT gate_code, count(*)
                FROM candidate_gate_results
                WHERE validation_run_id = ?
                GROUP BY gate_code
                ORDER BY gate_code
                """,
                [validation_run_id],
            )
            .fetchall()
        )
        return LexicalAuditReport(
            validation_run_id=validation_run_id,
            candidate_state_counts=dict(sorted(state_counts.items())),
            gate_code_counts={str(code): int(count) for code, count in gate_rows},
        )

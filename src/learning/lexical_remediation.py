"""Deterministic remediation of every imported lexical definition input."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.learning.lexical_evidence import (
    EvidenceSelection,
    LexicalEvidenceRepository,
    LexicalEvidenceSelector,
)
from src.learning.models import (
    CandidateState,
    EvidenceRole,
    InputDisposition,
    InputDispositionState,
    RemediationRunReport,
)
from src.learning.quality import GateReport, QualityGate, cefr_for_rank
from src.learning.repository import ContentRepository
from src.learning.store import LearningGraphStore

LEXICAL_REMEDIATION_POLICY_VERSION = "lexical-source-evidence-v1"
LEXICAL_REMEDIATION_SELECTION = {
    "content_type": "sense",
    "record_type": "sqlite_lexical_definition_evidence",
    "selection_policy": "verified-provenance,lemma,pos,translation,ipa,source-row-v1",
}
_REMEDIATION_PHASE = "remediation"
_BATCH_SIZE = 250


class LexicalRemediationService:
    """Produce only validated or quarantined candidates from imported evidence.

    This service never calls an approval transition.  Human/editorial review
    remains the only path to approved canonical content.
    """

    def __init__(
        self,
        store: LearningGraphStore,
        quality_gate: QualityGate | None = None,
        repository: ContentRepository | None = None,
        evidence_repository: LexicalEvidenceRepository | None = None,
        selector: LexicalEvidenceSelector | None = None,
    ) -> None:
        self.store = store
        self.quality_gate = quality_gate or QualityGate()
        self.repository = repository or ContentRepository(store)
        self.evidence_repository = evidence_repository or LexicalEvidenceRepository(
            store
        )
        self.selector = selector or LexicalEvidenceSelector()

    def run(
        self,
        snapshot_id: str,
        *,
        validation_run_id: str | None = None,
        interrupt_after: int | None = None,
    ) -> RemediationRunReport:
        """Process a snapshot in stable 250-input batches and resume safely."""
        run_id = validation_run_id or str(uuid4())
        self.evidence_repository.create_validation_run(
            run_id,
            snapshot_id,
            LEXICAL_REMEDIATION_POLICY_VERSION,
            LEXICAL_REMEDIATION_SELECTION,
        )
        checkpoint = self.evidence_repository.get_checkpoint(run_id, _REMEDIATION_PHASE)
        if checkpoint is not None and checkpoint.completed_at is not None:
            return self._report(run_id, snapshot_id, checkpoint.processed_count)

        processed_count = 0 if checkpoint is None else checkpoint.processed_count
        after_input_key = None if checkpoint is None else checkpoint.last_input_key
        processed_this_call = 0
        while True:
            input_ids = self.evidence_repository.list_input_ids(
                snapshot_id, after_input_key=after_input_key, limit=_BATCH_SIZE
            )
            if not input_ids:
                self.evidence_repository.write_checkpoint(
                    run_id,
                    _REMEDIATION_PHASE,
                    after_input_key,
                    processed_count,
                    completed=True,
                )
                self._complete_validation_run(run_id)
                return self._report(run_id, snapshot_id, processed_count)
            for input_id in input_ids:
                bundle = self.evidence_repository.get_input(input_id)
                existing = self.evidence_repository.get_disposition(run_id, input_id)
                if existing is None:
                    self._remediate(bundle, run_id, retry=False)
                after_input_key = bundle.lexical_input.input_key
                processed_count += 1
                processed_this_call += 1
                self.evidence_repository.write_checkpoint(
                    run_id,
                    _REMEDIATION_PHASE,
                    after_input_key,
                    processed_count,
                    completed=False,
                )
                if (
                    interrupt_after is not None
                    and processed_this_call >= interrupt_after
                ):
                    raise RuntimeError("remediation interrupted after checkpoint")

    def retry_input(self, validation_run_id: str, input_id: str) -> InputDisposition:
        """Return the existing outcome for an immutable quarantined input.

        Source evidence and the deterministic policy are immutable within a
        validation run, so repeating this request cannot produce a new
        selection.  Recording another attempt would only duplicate audit
        history; a later adjudication run must use a different policy/run.
        """
        existing = self.evidence_repository.get_disposition(validation_run_id, input_id)
        if existing is None:
            raise ValueError("cannot retry an input without a prior disposition")
        if existing.state is not InputDispositionState.QUARANTINED:
            raise ValueError("only a quarantined input may be retried")
        return existing

    def _remediate(
        self,
        bundle: Any,
        validation_run_id: str,
        *,
        retry: bool,
    ) -> InputDisposition:
        selection = self.selector.select(bundle)
        self.evidence_repository.upsert_rankings(
            validation_run_id, selection.rankings(validation_run_id)
        )
        self.evidence_repository.upsert_source_rankings(
            validation_run_id, selection.source_rankings(validation_run_id)
        )
        payload = self._candidate_payload(selection)
        candidate_id = self.repository.create_candidate(
            bundle.lexical_input.raw_record_id,
            "sense",
            payload,
            self._candidate_evidence(selection),
            1.0,
        )
        canonical_key = str(payload["stable_key"])
        self.evidence_repository.map_input(
            bundle.lexical_input.input_id, canonical_key, candidate_id
        )

        structural = self.quality_gate.validate_payload("sense", payload, candidate_id)
        source = self.quality_gate.validate_lexical_source_evidence(
            selection, candidate_id
        )
        combined = GateReport(failures=[*source.failures, *structural.failures])
        self.evidence_repository.persist_candidate_gate_results(
            validation_run_id,
            candidate_id,
            selection.failures,
            [(failure.code, failure.message) for failure in structural.failures],
        )

        if combined.passed:
            self._mark_validated(candidate_id)
            outcome = InputDispositionState.VALIDATED
        else:
            self._mark_quarantined(candidate_id, combined)
            outcome = InputDispositionState.QUARANTINED
        failure_codes = [failure.code for failure in combined.failures]
        rationale = {
            "canonical_key": canonical_key,
            "selected_evidence_ids": [
                item.evidence.evidence_id for item in selection.selected
            ],
            "source_failure_codes": list(selection.failure_codes),
            "structural_failure_codes": [
                failure.code for failure in structural.failures
            ],
            "source_evidence_inventory": selection.source_inventory(),
        }
        disposition = InputDisposition(
            validation_run_id=validation_run_id,
            input_id=bundle.lexical_input.input_id,
            state=outcome,
            candidate_id=candidate_id,
            failure_codes=failure_codes,
            rationale=rationale,
            updated_at=datetime.now(UTC),
        )
        self.evidence_repository.upsert_disposition(disposition)
        self.evidence_repository.append_attempt(
            validation_run_id,
            bundle.lexical_input.input_id,
            self._selection_for_attempt(selection),
            outcome,
            failure_codes,
            rationale,
        )
        if outcome is InputDispositionState.QUARANTINED:
            self.evidence_repository.upsert_quarantine_case(
                bundle.lexical_input.input_id,
                validation_run_id,
                failure_codes,
                selection.alternatives(),
                retry=retry,
            )
        else:
            self.evidence_repository.resolve_quarantine_case(
                bundle.lexical_input.input_id, validation_run_id
            )
        return disposition

    def _mark_validated(self, candidate_id: str) -> None:
        state = self.store.fetch_value(
            "SELECT state FROM content_candidates WHERE candidate_id = ?",
            [candidate_id],
        )
        if state == CandidateState.CANDIDATE.value:
            self.repository.mark_candidate_validated(candidate_id)
        elif state != CandidateState.VALIDATED.value:
            raise ValueError(
                "a quarantined or reviewed candidate cannot become validated"
            )

    def _mark_quarantined(self, candidate_id: str, report: GateReport) -> None:
        state = self.store.fetch_value(
            "SELECT state FROM content_candidates WHERE candidate_id = ?",
            [candidate_id],
        )
        if state in {CandidateState.CANDIDATE.value, CandidateState.VALIDATED.value}:
            self.repository.review_candidate(
                candidate_id,
                CandidateState.QUARANTINED.value,
                "validator:lexical-source-evidence-v1",
                ",".join(failure.code for failure in report.failures),
            )
        elif state != CandidateState.QUARANTINED.value:
            raise ValueError("a reviewed candidate cannot be remediated automatically")

    @staticmethod
    def _candidate_payload(selection: EvidenceSelection) -> dict[str, Any]:
        bundle = selection.bundle
        definition_items = selection.selected_by_role(EvidenceRole.DEFINITION)
        definition = (
            definition_items[0].evidence.value
            if definition_items and isinstance(definition_items[0].evidence.value, dict)
            else {}
        )
        translation_items = selection.selected_by_role(EvidenceRole.TRANSLATION)
        translation = (
            translation_items[0].evidence.value
            if translation_items
            and isinstance(translation_items[0].evidence.value, dict)
            else {}
        )
        ipa_items = selection.selected_by_role(EvidenceRole.IPA)
        ipa_values: dict[str, str] = {}
        for item in ipa_items:
            value = item.evidence.value
            if (
                isinstance(value, dict)
                and isinstance(value.get("kind"), str)
                and isinstance(value.get("value"), str)
            ):
                ipa_values[value["kind"]] = value["value"]
        example_items = selection.selected_by_role(EvidenceRole.EXAMPLE)
        examples = [
            {
                "text_en": LexicalRemediationService._example_text(item.evidence.value),
                "text_vi": item.evidence.value.get("text_vi"),
                "source": item.evidence.source_name,
            }
            for item in example_items
            if isinstance(item.evidence.value, dict)
        ]
        lemma = LexicalRemediationService._stable_component(bundle.lexical_input.lemma)
        pos = LexicalRemediationService._stable_component(bundle.lexical_input.pos)
        definition_en = (
            definition.get("definition_en") if isinstance(definition, dict) else None
        )
        definition_text = definition_en if isinstance(definition_en, str) else ""
        definition_hash = hashlib.sha256(
            definition_text.casefold().encode("utf-8")
        ).hexdigest()[:12]
        translation_vi = (
            translation.get("text", translation.get("definition_vi"))
            if isinstance(translation, dict)
            else None
        )
        return {
            "stable_key": f"sense.{lemma}.{pos}.{definition_hash}",
            "lemma": bundle.lexical_input.lemma.strip().casefold(),
            "pos": bundle.lexical_input.pos.strip().casefold(),
            "frequency_rank": bundle.lexical_input.frequency_rank,
            "cefr_level": cefr_for_rank(bundle.lexical_input.frequency_rank),
            "cefr_method": "frequency_rank_v1",
            "definition_en": definition_en,
            "definition_vi": translation_vi,
            "ipa_uk": ipa_values.get("ipa_uk"),
            "ipa_us": ipa_values.get("ipa_us"),
            "ipa_source": bundle.source_asset_id if ipa_values else None,
            "ipa_confidence": 0.8 if ipa_values else 0.0,
            "examples": examples,
            "source_asset_id": bundle.source_asset_id,
        }

    @staticmethod
    def _candidate_evidence(selection: EvidenceSelection) -> dict[str, Any]:
        return {
            "input_id": selection.bundle.lexical_input.input_id,
            "selected": [
                {
                    "evidence_id": item.evidence.evidence_id,
                    "evidence_role": item.evidence.evidence_role.value,
                    "source_row_id": item.evidence.source_row_id,
                    "source_name": item.evidence.source_name,
                    "value": item.evidence.value,
                }
                for item in selection.selected
            ],
        }

    @staticmethod
    def _selection_for_attempt(selection: EvidenceSelection) -> dict[str, Any]:
        return {
            "selected_evidence_ids": [
                item.evidence.evidence_id for item in selection.selected
            ],
            "source_evidence_inventory": selection.source_inventory(),
            "source_failure_codes": list(selection.failure_codes),
        }

    @staticmethod
    def _example_text(value: Any) -> Any:
        if not isinstance(value, dict):
            return None
        return value.get("text_en", value.get("text"))

    @staticmethod
    def _stable_component(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return normalized or "unknown"

    def _complete_validation_run(self, validation_run_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE validation_runs SET completed_at = current_timestamp
                WHERE validation_run_id = ?
                """,
                [validation_run_id],
            )

    def _report(
        self, validation_run_id: str, snapshot_id: str, processed_count: int
    ) -> RemediationRunReport:
        counts = self.evidence_repository.disposition_counts(validation_run_id)
        failure_counts: Counter[str] = Counter()
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT failure_codes_json FROM lexical_input_dispositions
            WHERE validation_run_id = ?
            """,
                [validation_run_id],
            )
            .fetchall()
        )
        for (failure_codes_json,) in rows:
            failure_counts.update(json.loads(str(failure_codes_json)))
        completed_at = self.store.fetch_value(
            "SELECT completed_at FROM validation_runs WHERE validation_run_id = ?",
            [validation_run_id],
        )
        return RemediationRunReport(
            validation_run_id=validation_run_id,
            snapshot_id=snapshot_id,
            processed_count=processed_count,
            validated_count=counts.get(InputDispositionState.VALIDATED.value, 0),
            quarantined_count=counts.get(InputDispositionState.QUARANTINED.value, 0),
            rejected_count=counts.get(InputDispositionState.REJECTED.value, 0),
            failure_counts=dict(sorted(failure_counts.items())),
            completed_at=completed_at,
        )

"""Deterministic access and selection for imported lexical source evidence.

The imported lexical graph deliberately preserves every source row.  This module
does not manufacture evidence: it makes the deterministic, auditable choice of
which existing rows may support one source definition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.learning.models import (
    EvidenceItem,
    EvidenceRanking,
    EvidenceRole,
    InputDisposition,
    InputDispositionState,
    LexicalDefinitionInput,
    RemediationAttempt,
    canonical_json,
)
from src.learning.store import LearningGraphStore

_TRUSTED_SOURCE_NAMES = frozenset({"kaikki", "tatoeba", "wiktionary"})
_WORD_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?")


@dataclass(frozen=True)
class LexicalEvidenceBundle:
    """One imported definition together with every immutable evidence item."""

    lexical_input: LexicalDefinitionInput
    source_asset_id: str
    raw_payload: dict[str, Any]
    evidence: tuple[EvidenceItem, ...]


@dataclass(frozen=True)
class SourceEvidenceFailure:
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class RankedEvidence:
    evidence: EvidenceItem
    rank: int
    selected: bool
    eligible: bool
    reason: dict[str, Any]


@dataclass(frozen=True)
class EvidenceSelection:
    bundle: LexicalEvidenceBundle
    items: tuple[RankedEvidence, ...]
    failures: tuple[SourceEvidenceFailure, ...]

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(failure.code for failure in self.failures)

    @property
    def selected(self) -> tuple[RankedEvidence, ...]:
        return tuple(item for item in self.items if item.selected)

    def by_role(self, role: EvidenceRole) -> tuple[RankedEvidence, ...]:
        return tuple(item for item in self.items if item.evidence.evidence_role is role)

    def selected_by_role(self, role: EvidenceRole) -> tuple[RankedEvidence, ...]:
        return tuple(item for item in self.by_role(role) if item.selected)

    def rankings(self, validation_run_id: str) -> list[EvidenceRanking]:
        return [
            EvidenceRanking(
                validation_run_id=validation_run_id,
                input_id=self.bundle.lexical_input.input_id,
                evidence_id=item.evidence.evidence_id,
                evidence_role=item.evidence.evidence_role,
                rank=item.rank,
                selected=item.selected,
                eligible=item.eligible,
                reason=item.reason,
            )
            for item in self.items
        ]

    def alternatives(self) -> list[dict[str, Any]]:
        """Return unselected evidence needed to reproduce a quarantine decision."""
        return [
            {
                "evidence_id": item.evidence.evidence_id,
                "evidence_role": item.evidence.evidence_role.value,
                "source_row_id": item.evidence.source_row_id,
                "eligible": item.eligible,
                "rank": item.rank,
                "reason": item.reason,
            }
            for item in self.items
            if not item.selected
        ]


@dataclass(frozen=True)
class RunCheckpoint:
    validation_run_id: str
    phase: str
    last_input_key: str | None
    processed_count: int
    completed_at: datetime | None


class LexicalEvidenceRepository:
    """Repository boundary for immutable evidence and remediation state."""

    def __init__(self, store: LearningGraphStore) -> None:
        self.store = store

    def get_input(self, input_id: str) -> LexicalEvidenceBundle:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT input.input_id, input.snapshot_id, input.raw_record_id,
                   input.source_word_id, input.source_definition_id, input.input_key,
                   input.source_definition_sha256, input.lemma, input.pos,
                   input.frequency_rank, input.created_at,
                   snapshot.asset_id, raw.payload_json
            FROM lexical_definition_inputs AS input
            JOIN source_snapshots AS snapshot ON snapshot.snapshot_id = input.snapshot_id
            JOIN raw_reference_records AS raw ON raw.raw_record_id = input.raw_record_id
            WHERE input.input_id = ?
            """,
                [input_id],
            )
            .fetchone()
        )
        if row is None:
            raise ValueError(f"lexical input {input_id!r} does not exist")
        (
            stored_input_id,
            snapshot_id,
            raw_record_id,
            source_word_id,
            source_definition_id,
            input_key,
            source_definition_sha256,
            lemma,
            pos,
            frequency_rank,
            created_at,
            source_asset_id,
            raw_payload_json,
        ) = row
        lexical_input = LexicalDefinitionInput(
            input_id=str(stored_input_id),
            snapshot_id=str(snapshot_id),
            raw_record_id=str(raw_record_id),
            source_word_id=int(source_word_id),
            source_definition_id=int(source_definition_id),
            input_key=str(input_key),
            source_definition_sha256=str(source_definition_sha256),
            lemma=str(lemma),
            pos=str(pos),
            frequency_rank=int(frequency_rank),
            created_at=created_at,
        )
        evidence_rows = (
            self.store.connection()
            .execute(
                """
            SELECT evidence_id, input_id, evidence_role, source_row_id, source_name,
                   value_json, created_at
            FROM lexical_evidence_items
            WHERE input_id = ?
            ORDER BY CASE evidence_role
                       WHEN 'definition' THEN 1
                       WHEN 'translation' THEN 2
                       WHEN 'ipa' THEN 3
                       WHEN 'example' THEN 4
                     END,
                     source_row_id, evidence_id
            """,
                [input_id],
            )
            .fetchall()
        )
        evidence = tuple(
            EvidenceItem(
                evidence_id=str(evidence_id),
                input_id=str(stored_evidence_input_id),
                evidence_role=EvidenceRole(str(evidence_role)),
                source_row_id=int(source_row_id),
                source_name=str(source_name),
                value=json.loads(str(value_json)),
                created_at=evidence_created_at,
            )
            for (
                evidence_id,
                stored_evidence_input_id,
                evidence_role,
                source_row_id,
                source_name,
                value_json,
                evidence_created_at,
            ) in evidence_rows
        )
        raw_payload = json.loads(str(raw_payload_json))
        if not isinstance(raw_payload, dict):
            raise TypeError("lexical raw payload must be an object")
        return LexicalEvidenceBundle(
            lexical_input=lexical_input,
            source_asset_id=str(source_asset_id),
            raw_payload=raw_payload,
            evidence=evidence,
        )

    def list_input_ids(
        self,
        snapshot_id: str,
        *,
        after_input_key: str | None = None,
        limit: int = 250,
    ) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cursor: tuple[int, int, int, str] | None = None
        if after_input_key is not None:
            pointer = (
                self.store.connection()
                .execute(
                    """
                SELECT frequency_rank, source_word_id, source_definition_id, input_key
                FROM lexical_definition_inputs
                WHERE snapshot_id = ? AND input_key = ?
                """,
                    [snapshot_id, after_input_key],
                )
                .fetchone()
            )
            if pointer is None:
                raise ValueError("checkpoint references an unknown lexical input key")
            cursor = (
                int(pointer[0]),
                int(pointer[1]),
                int(pointer[2]),
                str(pointer[3]),
            )
        if cursor is None:
            rows = (
                self.store.connection()
                .execute(
                    """
                SELECT input_id FROM lexical_definition_inputs
                WHERE snapshot_id = ?
                ORDER BY frequency_rank, source_word_id, source_definition_id, input_key
                LIMIT ?
                """,
                    [snapshot_id, limit],
                )
                .fetchall()
            )
        else:
            rank, word_id, definition_id, input_key = cursor
            rows = (
                self.store.connection()
                .execute(
                    """
                SELECT input_id FROM lexical_definition_inputs
                WHERE snapshot_id = ?
                  AND (
                    frequency_rank > ?
                    OR (frequency_rank = ? AND source_word_id > ?)
                    OR (frequency_rank = ? AND source_word_id = ?
                        AND source_definition_id > ?)
                    OR (frequency_rank = ? AND source_word_id = ?
                        AND source_definition_id = ? AND input_key > ?)
                  )
                ORDER BY frequency_rank, source_word_id, source_definition_id, input_key
                LIMIT ?
                """,
                    [
                        snapshot_id,
                        rank,
                        rank,
                        word_id,
                        rank,
                        word_id,
                        definition_id,
                        rank,
                        word_id,
                        definition_id,
                        input_key,
                        limit,
                    ],
                )
                .fetchall()
            )
        return [str(row[0]) for row in rows]

    def create_validation_run(
        self,
        validation_run_id: str,
        snapshot_id: str,
        policy_version: str,
        selection: dict[str, Any],
    ) -> None:
        with self.store.transaction() as connection:
            existing = connection.execute(
                """
                SELECT snapshot_id, policy_version, selection_json
                FROM validation_runs WHERE validation_run_id = ?
                """,
                [validation_run_id],
            ).fetchone()
            selection_json = canonical_json(selection)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO validation_runs (
                        validation_run_id, snapshot_id, policy_version, selection_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [validation_run_id, snapshot_id, policy_version, selection_json],
                )
                return
            if tuple(map(str, existing)) != (
                snapshot_id,
                policy_version,
                selection_json,
            ):
                raise ValueError(
                    "validation run identity conflicts with its existing policy"
                )

    def upsert_rankings(
        self, validation_run_id: str, rankings: list[EvidenceRanking]
    ) -> None:
        if not rankings:
            return
        if any(ranking.validation_run_id != validation_run_id for ranking in rankings):
            raise ValueError("rankings must belong to one validation run")
        with self.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO lexical_evidence_rankings (
                    validation_run_id, input_id, evidence_id, evidence_role,
                    rank, selected, eligible, reason_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(validation_run_id, input_id, evidence_id) DO UPDATE SET
                    evidence_role = excluded.evidence_role,
                    rank = excluded.rank,
                    selected = excluded.selected,
                    eligible = excluded.eligible,
                    reason_json = excluded.reason_json
                """,
                [
                    (
                        ranking.validation_run_id,
                        ranking.input_id,
                        ranking.evidence_id,
                        ranking.evidence_role.value,
                        ranking.rank,
                        ranking.selected,
                        ranking.eligible,
                        ranking.reason_json,
                    )
                    for ranking in rankings
                ],
            )

    def get_disposition(
        self, validation_run_id: str, input_id: str
    ) -> InputDisposition | None:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT validation_run_id, input_id, state, candidate_id, failure_codes_json,
                   rationale_json, updated_at
            FROM lexical_input_dispositions
            WHERE validation_run_id = ? AND input_id = ?
            """,
                [validation_run_id, input_id],
            )
            .fetchone()
        )
        if row is None:
            return None
        return InputDisposition(
            validation_run_id=str(row[0]),
            input_id=str(row[1]),
            state=InputDispositionState(str(row[2])),
            candidate_id=None if row[3] is None else str(row[3]),
            failure_codes=json.loads(str(row[4])),
            rationale=json.loads(str(row[5])),
            updated_at=row[6],
        )

    def upsert_disposition(self, disposition: InputDisposition) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO lexical_input_dispositions (
                    validation_run_id, input_id, state, candidate_id,
                    failure_codes_json, rationale_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(validation_run_id, input_id) DO UPDATE SET
                    state = excluded.state,
                    candidate_id = excluded.candidate_id,
                    failure_codes_json = excluded.failure_codes_json,
                    rationale_json = excluded.rationale_json,
                    updated_at = excluded.updated_at
                """,
                [
                    disposition.validation_run_id,
                    disposition.input_id,
                    disposition.state.value,
                    disposition.candidate_id,
                    disposition.failure_codes_json,
                    disposition.rationale_json,
                    disposition.updated_at,
                ],
            )

    def append_attempt(
        self,
        validation_run_id: str,
        input_id: str,
        selection: dict[str, Any],
        outcome: InputDispositionState,
        failure_codes: list[str],
        rationale: dict[str, Any],
    ) -> RemediationAttempt:
        with self.store.transaction() as connection:
            attempt_number = int(
                connection.execute(
                    """
                    SELECT coalesce(max(attempt_number), 0) + 1
                    FROM lexical_remediation_attempts
                    WHERE validation_run_id = ? AND input_id = ?
                    """,
                    [validation_run_id, input_id],
                ).fetchone()[0]
            )
            attempt = RemediationAttempt(
                attempt_id=str(uuid4()),
                validation_run_id=validation_run_id,
                input_id=input_id,
                attempt_number=attempt_number,
                selection=selection,
                outcome=outcome,
                failure_codes=failure_codes,
                rationale=rationale,
                created_at=datetime.now(UTC),
            )
            connection.execute(
                """
                INSERT INTO lexical_remediation_attempts (
                    attempt_id, validation_run_id, input_id, attempt_number,
                    selection_json, outcome, failure_codes_json, rationale_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    attempt.attempt_id,
                    attempt.validation_run_id,
                    attempt.input_id,
                    attempt.attempt_number,
                    attempt.selection_json,
                    attempt.outcome.value,
                    attempt.failure_codes_json,
                    attempt.rationale_json,
                    attempt.created_at,
                ],
            )
            return attempt

    def map_input(
        self, input_id: str, canonical_key: str, candidate_id: str | None
    ) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO lexical_input_canonical_map (
                    input_id, canonical_key, candidate_id
                ) VALUES (?, ?, ?)
                ON CONFLICT(input_id) DO UPDATE SET
                    canonical_key = excluded.canonical_key,
                    candidate_id = excluded.candidate_id,
                    mapped_at = now()
                """,
                [input_id, canonical_key, candidate_id],
            )

    def upsert_quarantine_case(
        self,
        input_id: str,
        validation_run_id: str,
        failure_codes: list[str],
        alternatives: list[dict[str, Any]],
        *,
        retry: bool,
    ) -> None:
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT case_id, retry_count FROM lexical_quarantine_cases WHERE input_id = ?",
                [input_id],
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO lexical_quarantine_cases (
                        case_id, input_id, latest_validation_run_id, status, retry_count,
                        failure_codes_json, alternatives_json
                    ) VALUES (?, ?, ?, 'open', ?, ?, ?)
                    """,
                    [
                        str(uuid4()),
                        input_id,
                        validation_run_id,
                        1 if retry else 0,
                        canonical_json(failure_codes),
                        canonical_json(alternatives),
                    ],
                )
            else:
                connection.execute(
                    """
                    UPDATE lexical_quarantine_cases
                    SET latest_validation_run_id = ?, status = 'open',
                        retry_count = ?, failure_codes_json = ?, alternatives_json = ?,
                        updated_at = current_timestamp
                    WHERE input_id = ?
                    """,
                    [
                        validation_run_id,
                        int(existing[1]) + (1 if retry else 0),
                        canonical_json(failure_codes),
                        canonical_json(alternatives),
                        input_id,
                    ],
                )

    def resolve_quarantine_case(self, input_id: str, validation_run_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE lexical_quarantine_cases
                SET latest_validation_run_id = ?, status = 'resolved', updated_at = current_timestamp
                WHERE input_id = ? AND status = 'open'
                """,
                [validation_run_id, input_id],
            )

    def get_checkpoint(
        self, validation_run_id: str, phase: str
    ) -> RunCheckpoint | None:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT validation_run_id, phase, last_input_key, processed_count, completed_at
            FROM lexical_run_checkpoints
            WHERE validation_run_id = ? AND phase = ?
            """,
                [validation_run_id, phase],
            )
            .fetchone()
        )
        if row is None:
            return None
        return RunCheckpoint(
            validation_run_id=str(row[0]),
            phase=str(row[1]),
            last_input_key=None if row[2] is None else str(row[2]),
            processed_count=int(row[3]),
            completed_at=row[4],
        )

    def write_checkpoint(
        self,
        validation_run_id: str,
        phase: str,
        last_input_key: str | None,
        processed_count: int,
        *,
        completed: bool,
    ) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO lexical_run_checkpoints (
                    validation_run_id, phase, last_input_key, processed_count, completed_at
                ) VALUES (?, ?, ?, ?, CASE WHEN ? THEN now() ELSE NULL END)
                ON CONFLICT(validation_run_id, phase) DO UPDATE SET
                    last_input_key = excluded.last_input_key,
                    processed_count = excluded.processed_count,
                    completed_at = excluded.completed_at,
                    updated_at = now()
                """,
                [validation_run_id, phase, last_input_key, processed_count, completed],
            )

    def persist_candidate_gate_results(
        self,
        validation_run_id: str,
        candidate_id: str,
        failures: tuple[SourceEvidenceFailure, ...],
        structural_failures: list[tuple[str, str]],
    ) -> None:
        outcomes = [
            (failure.code, False, failure.message, canonical_json(failure.details))
            for failure in failures
        ] + [
            (code, False, message, canonical_json({}))
            for code, message in structural_failures
        ]
        if not outcomes:
            outcomes = [
                (
                    "lexical_evidence.complete",
                    True,
                    "All lexical source-evidence and structural gates passed",
                    canonical_json({}),
                )
            ]
        with self.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO candidate_gate_results (
                    validation_run_id, candidate_id, gate_code, passed, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(validation_run_id, candidate_id, gate_code) DO UPDATE SET
                    passed = excluded.passed,
                    message = excluded.message,
                    details_json = excluded.details_json
                """,
                [
                    (
                        validation_run_id,
                        candidate_id,
                        code,
                        passed,
                        message,
                        details_json,
                    )
                    for code, passed, message, details_json in outcomes
                ],
            )

    def selection_signature(self, validation_run_id: str) -> list[tuple[Any, ...]]:
        return (
            self.store.connection()
            .execute(
                """
            SELECT input_id, evidence_id, evidence_role, rank, selected, eligible, reason_json
            FROM lexical_evidence_rankings
            WHERE validation_run_id = ?
            ORDER BY input_id, evidence_role, rank, evidence_id
            """,
                [validation_run_id],
            )
            .fetchall()
        )

    def disposition_counts(self, validation_run_id: str) -> dict[str, int]:
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT state, count(*) FROM lexical_input_dispositions
            WHERE validation_run_id = ? GROUP BY state ORDER BY state
            """,
                [validation_run_id],
            )
            .fetchall()
        )
        return {str(state): int(count) for state, count in rows}


class LexicalEvidenceSelector:
    """Rank only immutable rows; no AI or generated substitute is permitted here."""

    def select(self, bundle: LexicalEvidenceBundle) -> EvidenceSelection:
        assessed = [self._assess(bundle, evidence) for evidence in bundle.evidence]
        ranked: list[RankedEvidence] = []
        for role in EvidenceRole:
            items = [item for item in assessed if item[0].evidence_role is role]
            items.sort(key=lambda item: self._sort_key(item[1], item[0]))
            selected_count = 0
            selected_ipa_kinds: set[str] = set()
            for index, (evidence, assessment) in enumerate(items, start=1):
                selected = assessment["eligible"]
                if role is EvidenceRole.IPA:
                    kind = str(assessment["ipa_kind"])
                    selected = selected and kind not in selected_ipa_kinds
                    if selected:
                        selected_ipa_kinds.add(kind)
                else:
                    selected = selected and selected_count == 0
                if selected:
                    selected_count += 1
                reason = {
                    "verified_provenance": assessment["verified_provenance"],
                    "lemma_match": assessment["lemma_match"],
                    "pos_or_form_compatible": assessment["pos_or_form_compatible"],
                    "translation_quality": assessment["translation_quality"],
                    "trusted_ipa": assessment["trusted_ipa"],
                    "source_row_id": evidence.source_row_id,
                    "semantic_compatible": assessment["semantic_compatible"],
                    "eligibility_reason": assessment["eligibility_reason"],
                }
                ranked.append(
                    RankedEvidence(
                        evidence=evidence,
                        rank=index,
                        selected=selected,
                        eligible=bool(assessment["eligible"]),
                        reason=reason,
                    )
                )
        failures = self._failures(bundle, tuple(ranked))
        return EvidenceSelection(bundle=bundle, items=tuple(ranked), failures=failures)

    def _assess(
        self, bundle: LexicalEvidenceBundle, evidence: EvidenceItem
    ) -> tuple[EvidenceItem, dict[str, Any]]:
        value = evidence.value if isinstance(evidence.value, dict) else {}
        source_name = evidence.source_name.strip().casefold()
        verified_provenance = (
            evidence.source_row_id > 0 and source_name in _TRUSTED_SOURCE_NAMES
        )
        lemma_match = "not_applicable"
        pos_compatible = True
        translation_quality = "not_applicable"
        trusted_ipa = False
        semantic_compatible = True
        eligible = False
        eligibility_reason = "unsupported evidence role"
        ipa_kind = ""
        lexical_input = bundle.lexical_input
        if evidence.evidence_role is EvidenceRole.DEFINITION:
            source_definition_id = value.get("definition_id", value.get("id"))
            source_matches = (
                source_definition_id is None
                or int(source_definition_id) == lexical_input.source_definition_id
            )
            pos_compatible = self._value_pos_compatible(value, lexical_input.pos)
            eligible = (
                source_matches
                and self._nonblank(value.get("definition_en"))
                and pos_compatible
            )
            eligibility_reason = (
                "target definition" if eligible else "not target definition"
            )
        elif evidence.evidence_role is EvidenceRole.TRANSLATION:
            definition_id = value.get("definition_id")
            source_matches = (
                definition_id is None
                or int(definition_id) == lexical_input.source_definition_id
            )
            pos_compatible = self._value_pos_compatible(value, lexical_input.pos)
            text = value.get("text", value.get("definition_vi"))
            translation_quality = self._translation_quality(text, source_name)
            eligible = (
                source_matches and pos_compatible and translation_quality == "verified"
            )
            eligibility_reason = (
                "verified translation" if eligible else "translation unavailable"
            )
        elif evidence.evidence_role is EvidenceRole.IPA:
            ipa_kind = str(value.get("kind", ""))
            ipa_value = value.get("value")
            trusted_ipa = (
                self._nonblank(ipa_value) and source_name in _TRUSTED_SOURCE_NAMES
            )
            eligible = trusted_ipa and ipa_kind in {"ipa_uk", "ipa_us"}
            eligibility_reason = (
                "trusted IPA" if eligible else "IPA is missing or unverified"
            )
        elif evidence.evidence_role is EvidenceRole.EXAMPLE:
            text_en = self._example_en(value)
            text_vi = value.get("text_vi")
            lemma_match = self._lemma_match(lexical_input.lemma, text_en)
            pos_compatible = self._example_pos_compatible(
                lexical_input.lemma, lexical_input.pos, text_en
            )
            semantic_compatible = self._example_sense_compatible(
                lexical_input.lemma,
                lexical_input.pos,
                self._definition_text(bundle),
                text_en,
            )
            translation_quality = self._translation_quality(text_vi, source_name)
            # A direct definition example is direct source evidence. A weak word
            # linkage remains an alternative but is not equally verified for this
            # specific definition.
            if value.get("kind") == "linked" and int(value.get("link_rank", 1)) > 1:
                verified_provenance = False
            eligible = (
                lemma_match != "missing"
                and pos_compatible
                and semantic_compatible
                and translation_quality == "verified"
            )
            eligibility_reason = (
                "aligned source example"
                if eligible
                else "example cannot prove this sense"
            )
        return evidence, {
            "verified_provenance": verified_provenance,
            "lemma_match": lemma_match,
            "pos_or_form_compatible": pos_compatible,
            "translation_quality": translation_quality,
            "trusted_ipa": trusted_ipa,
            "semantic_compatible": semantic_compatible,
            "eligible": eligible,
            "eligibility_reason": eligibility_reason,
            "ipa_kind": ipa_kind,
        }

    @staticmethod
    def _sort_key(
        assessment: dict[str, Any], evidence: EvidenceItem
    ) -> tuple[Any, ...]:
        """The documented policy order, followed by stable source identity."""
        return (
            -int(bool(assessment["verified_provenance"])),
            -int(assessment["lemma_match"] in {"exact", "inflection"}),
            -int(bool(assessment["pos_or_form_compatible"])),
            -int(assessment["translation_quality"] == "verified"),
            -int(bool(assessment["trusted_ipa"])),
            evidence.source_row_id,
            evidence.evidence_id,
        )

    def _failures(
        self, bundle: LexicalEvidenceBundle, ranked: tuple[RankedEvidence, ...]
    ) -> tuple[SourceEvidenceFailure, ...]:
        failures: list[SourceEvidenceFailure] = []
        selected = [item for item in ranked if item.selected]
        if not selected or any(
            not bool(item.reason["verified_provenance"]) for item in selected
        ):
            failures.append(
                SourceEvidenceFailure(
                    "provenance.incomplete",
                    "Selected source evidence requires a trusted source and row identifier",
                    {
                        "selected_evidence_ids": [
                            item.evidence.evidence_id for item in selected
                        ]
                    },
                )
            )

        examples = [
            item
            for item in ranked
            if item.evidence.evidence_role is EvidenceRole.EXAMPLE
        ]
        selected_examples = [item for item in examples if item.selected]
        if not selected_examples:
            if examples and all(
                item.reason["lemma_match"] == "missing" for item in examples
            ):
                failures.append(
                    SourceEvidenceFailure(
                        "example.lemma_missing",
                        "No source example contains the lemma or a recognized inflection",
                        {
                            "evidence_ids": [
                                item.evidence.evidence_id for item in examples
                            ]
                        },
                    )
                )
            elif examples and all(
                not bool(item.reason["pos_or_form_compatible"]) for item in examples
            ):
                failures.append(
                    SourceEvidenceFailure(
                        "example.pos_or_form_mismatch",
                        "Source examples use a different part of speech or form",
                        {
                            "evidence_ids": [
                                item.evidence.evidence_id for item in examples
                            ]
                        },
                    )
                )
            else:
                failures.append(
                    SourceEvidenceFailure(
                        "example.sense_unproven",
                        "No selected source example proves the imported definition's sense",
                        {
                            "evidence_ids": [
                                item.evidence.evidence_id for item in examples
                            ]
                        },
                    )
                )

        translations = [
            item
            for item in ranked
            if item.evidence.evidence_role is EvidenceRole.TRANSLATION
        ]
        selected_translations = [item for item in translations if item.selected]
        if not selected_translations:
            unknown_translations = [
                item
                for item in translations
                if item.reason["translation_quality"] == "unknown"
            ]
            if unknown_translations:
                failures.append(
                    SourceEvidenceFailure(
                        "translation.quality_unknown",
                        "Available Vietnamese translations lack trusted quality evidence",
                        {
                            "evidence_ids": [
                                item.evidence.evidence_id
                                for item in unknown_translations
                            ]
                        },
                    )
                )
                return self._append_ipa_and_conflict_failures(bundle, ranked, failures)
            failures.append(
                SourceEvidenceFailure(
                    "translation.missing_or_invalid",
                    "A selected definition requires a non-placeholder Vietnamese translation",
                    {
                        "evidence_ids": [
                            item.evidence.evidence_id for item in translations
                        ]
                    },
                )
            )
        elif any(
            item.reason["translation_quality"] != "verified"
            for item in selected_translations
        ):
            failures.append(
                SourceEvidenceFailure(
                    "translation.quality_unknown",
                    "The selected Vietnamese translation has no trusted quality evidence",
                    {
                        "evidence_ids": [
                            item.evidence.evidence_id for item in selected_translations
                        ]
                    },
                )
            )

        return self._append_ipa_and_conflict_failures(bundle, ranked, failures)

    @staticmethod
    def _append_ipa_and_conflict_failures(
        bundle: LexicalEvidenceBundle,
        ranked: tuple[RankedEvidence, ...],
        failures: list[SourceEvidenceFailure],
    ) -> tuple[SourceEvidenceFailure, ...]:
        ipas = [
            item for item in ranked if item.evidence.evidence_role is EvidenceRole.IPA
        ]
        if not any(item.selected for item in ipas):
            failures.append(
                SourceEvidenceFailure(
                    "ipa.missing_or_unverified",
                    "A selected definition requires trusted IPA evidence",
                    {"evidence_ids": [item.evidence.evidence_id for item in ipas]},
                )
            )

        if LexicalEvidenceSelector._has_conflict(bundle, ranked):
            failures.append(
                SourceEvidenceFailure(
                    "source_evidence_conflict",
                    "Source evidence has conflicting POS or translations for this definition",
                    {"input_id": bundle.lexical_input.input_id},
                )
            )
        return tuple(failures)

    @staticmethod
    def _has_conflict(
        bundle: LexicalEvidenceBundle, ranked: tuple[RankedEvidence, ...]
    ) -> bool:
        lexical_input = bundle.lexical_input
        declared_pos: set[str] = set()
        translations: set[str] = set()
        for item in ranked:
            value = item.evidence.value if isinstance(item.evidence.value, dict) else {}
            source_definition_id = value.get("definition_id", value.get("id"))
            if source_definition_id is not None:
                try:
                    if int(source_definition_id) != lexical_input.source_definition_id:
                        continue
                except (TypeError, ValueError):
                    return True
            value_pos = value.get("pos")
            if isinstance(value_pos, str) and value_pos.strip():
                declared_pos.add(value_pos.strip().casefold())
            if item.evidence.evidence_role is EvidenceRole.TRANSLATION:
                text = value.get("text", value.get("definition_vi"))
                if isinstance(text, str) and text.strip():
                    translations.add(" ".join(text.casefold().split()))
        return (
            any(pos != lexical_input.pos.casefold() for pos in declared_pos)
            or len(declared_pos) > 1
            or len(translations) > 1
        )

    @staticmethod
    def _value_pos_compatible(value: dict[str, Any], expected_pos: str) -> bool:
        declared_pos = value.get("pos")
        return (
            not isinstance(declared_pos, str)
            or not declared_pos.strip()
            or (declared_pos.strip().casefold() == expected_pos.casefold())
        )

    @staticmethod
    def _translation_quality(text: Any, source_name: str) -> str:
        if not LexicalEvidenceSelector._nonblank(text):
            return "missing"
        normalized = " ".join(str(text).casefold().split())
        if normalized.startswith("[vi]"):
            return "invalid"
        if source_name in _TRUSTED_SOURCE_NAMES:
            return "verified"
        return "unknown"

    @staticmethod
    def _example_en(value: dict[str, Any]) -> str:
        text = value.get("text_en", value.get("text"))
        return text if isinstance(text, str) else ""

    @staticmethod
    def _definition_text(bundle: LexicalEvidenceBundle) -> str:
        definition = bundle.raw_payload.get("definition")
        if isinstance(definition, dict):
            value = definition.get("definition_en")
            return value if isinstance(value, str) else ""
        return ""

    @staticmethod
    def _lemma_match(lemma: str, text: str) -> str:
        words = _WORD_PATTERN.findall(text.casefold())
        normalized_lemma = lemma.casefold()
        if normalized_lemma in words:
            return "exact"
        if any(
            LexicalEvidenceSelector._is_inflection(normalized_lemma, word)
            for word in words
        ):
            return "inflection"
        return "missing"

    @staticmethod
    def _is_inflection(lemma: str, word: str) -> bool:
        if lemma == "do":
            return word in {"does", "did", "doing", "done"}
        if (
            word == f"{lemma}s"
            or word == f"{lemma}es"
            or word == f"{lemma}ed"
            or word == f"{lemma}ing"
        ):
            return True
        return lemma.endswith("y") and word in {
            f"{lemma[:-1]}ies",
            f"{lemma[:-1]}ied",
        }

    @staticmethod
    def _example_pos_compatible(lemma: str, pos: str, text: str) -> bool:
        words = _WORD_PATTERN.findall(text.casefold())
        normalized_lemma = lemma.casefold()
        indices = [
            index
            for index, word in enumerate(words)
            if word == normalized_lemma
            or LexicalEvidenceSelector._is_inflection(normalized_lemma, word)
        ]
        if not indices:
            return False
        if normalized_lemma == "do" and pos.casefold() == "verb":
            return not any(
                words[index] in {"do", "does", "did"}
                and index + 1 < len(words)
                and words[index + 1]
                in {"not", "n't", "you", "we", "they", "i", "he", "she", "it"}
                for index in indices
            )
        if normalized_lemma == "word" and pos.casefold() == "verb":
            return not any(
                index > 0
                and words[index - 1] in {"a", "an", "the", "this", "that", "new"}
                for index in indices
            )
        return True

    @staticmethod
    def _example_sense_compatible(
        lemma: str, pos: str, definition: str, text: str
    ) -> bool:
        normalized_definition = definition.casefold()
        normalized_text = text.casefold().lstrip()
        if lemma.casefold() == "yet":
            temporal = any(
                phrase in normalized_definition
                for phrase in ("until the present", "so far", "up to now")
            )
            concessive_example = (
                normalized_text.startswith("yet ") or ", yet " in normalized_text
            )
            concessive = any(
                phrase in normalized_definition
                for phrase in ("nevertheless", "despite", "however")
            )
            temporal_example = normalized_text.endswith((" yet.", " yet?"))
            if temporal and concessive_example:
                return False
            if concessive and temporal_example:
                return False
        return True

    @staticmethod
    def _nonblank(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

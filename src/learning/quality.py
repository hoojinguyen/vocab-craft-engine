from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GateFailure:
    code: str
    message: str
    revision_id: str | None = None


@dataclass
class GateReport:
    failures: list[GateFailure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def add(self, code: str, message: str, revision_id: str | None = None) -> None:
        self.failures.append(GateFailure(code, message, revision_id))


class QualityGate:
    """Validate publishability of canonical learning content and graph semantics."""

    def validate_revision(self, revision: dict[str, Any]) -> GateReport:
        report = GateReport()
        payload = revision.get("payload", {})
        revision_id = revision.get("revision_id")
        content_type = revision.get("content_type", "unknown")
        if revision.get("review_state") != "approved":
            report.add(
                "revision.not_approved",
                "Only approved revisions may be published",
                revision_id,
            )
        if not payload.get("stable_key"):
            report.add(
                "revision.stable_key_missing", "A stable_key is required", revision_id
            )

        validator = getattr(self, f"_validate_{content_type}", None)
        if validator is not None:
            validator(payload, report, revision_id)
        return report

    def validate_graph(
        self, revisions: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> GateReport:
        report = GateReport()
        for revision in revisions:
            report.failures.extend(self.validate_revision(revision).failures)

        revisions_by_id = {
            str(revision.get("revision_id")): revision
            for revision in revisions
            if revision.get("revision_id") is not None
        }
        for scenario in revisions:
            if scenario.get("content_type") != "scenario":
                continue
            if scenario.get("review_state") != "approved":
                continue
            self._validate_scenario_graph(scenario, revisions_by_id, edges, report)
        return report

    def summarize(self, revisions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {
            "review_states": {},
            "source_assets": {},
            "cefr_levels": {},
        }
        for revision in revisions:
            payload = revision.get("payload", {})
            values = (
                ("review_states", revision.get("review_state", "unknown")),
                ("source_assets", revision.get("source_asset_id", "unknown")),
                ("cefr_levels", payload.get("cefr_level", "unassigned")),
            )
            for bucket, value in values:
                key = str(value)
                summary[bucket][key] = summary[bucket].get(key, 0) + 1
        return summary

    def _validate_module(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload, report, revision_id, "module", "code", "title", "cefr_level"
        )

    def _validate_objective(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload, report, revision_id, "objective", "code", "outcome", "cefr_level"
        )
        if not payload.get("success_criteria"):
            report.add(
                "objective.success_criteria_missing",
                "An objective requires non-empty success criteria",
                revision_id,
            )
        if not payload.get("cefr_method"):
            report.add(
                "objective.level_evidence_missing",
                "An objective requires a calibrated CEFR method",
                revision_id,
            )

    def _validate_lexeme(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(payload, report, revision_id, "lexeme", "lemma")
        ipa_us, ipa_uk = payload.get("ipa_us"), payload.get("ipa_uk")
        if not ipa_us and not ipa_uk:
            return
        confidence = payload.get("ipa_confidence")
        is_verified = (
            bool(payload.get("ipa_source"))
            and isinstance(confidence, (int, float))
            and confidence >= 0.8
            and (
                ipa_us != ipa_uk or payload.get("ipa_variant_status") == "same_verified"
            )
        )
        if not is_verified:
            report.add(
                "lexeme.ipa_unverified",
                "IPA requires a trusted source, confidence, and verified variant status",
                revision_id,
            )

    def _validate_form(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(payload, report, revision_id, "form", "written_form", "form_kind")

    def _validate_chunk(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload, report, revision_id, "chunk", "text_en", "text_vi", "usage_note"
        )

    def _validate_pattern(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "pattern",
            "form",
            "communicative_function",
            "example_frame",
        )

    def _validate_sentence(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(payload, report, revision_id, "sentence", "text_en", "cefr_level")
        if not payload.get("text_vi"):
            report.add(
                "sentence.translation_missing",
                "A sentence requires a reviewed Vietnamese translation",
                revision_id,
            )
        if not payload.get("cefr_method"):
            report.add(
                "sentence.level_evidence_missing",
                "A sentence requires CEFR level evidence",
                revision_id,
            )
        if not self._minimum_score(payload.get("naturalness_score"), 0.8):
            report.add(
                "sentence.naturalness_unverified",
                "A sentence requires naturalness_score >= 0.8",
                revision_id,
            )
        if payload.get("translation_reviewed") is not True:
            report.add(
                "sentence.translation_unreviewed",
                "A sentence translation must be reviewed",
                revision_id,
            )
        if payload.get("audio_required") and (
            not payload.get("audio_asset_id")
            or payload.get("audio_alignment_status") != "verified"
        ):
            report.add(
                "sentence.audio_unverified",
                "Required sentence audio must be present and aligned",
                revision_id,
            )

    def _validate_audio_asset(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "audio_asset",
            "asset_sha256",
            "locale",
            "voice_or_speaker",
            "source_asset_id",
        )
        if payload.get("license_status") != "approved":
            report.add(
                "audio_asset.license_unapproved",
                "Audio assets require approved rights evidence",
                revision_id,
            )
        if payload.get("transcript_alignment_status") != "verified":
            report.add(
                "audio_asset.alignment_unverified",
                "Audio transcript alignment must be verified",
                revision_id,
            )

    def _validate_scenario(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "scenario",
            "goal",
            "register",
            "end_condition",
        )
        if not isinstance(payload.get("roles"), list) or len(payload["roles"]) < 2:
            report.add(
                "scenario.roles_invalid",
                "A scenario requires at least two roles",
                revision_id,
            )
        if payload.get("practice_mode") not in {"linear", "branching"}:
            report.add(
                "scenario.practice_mode_invalid",
                "A scenario practice mode must be linear or branching",
                revision_id,
            )

    def _validate_dialogue_turn(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "dialogue_turn",
            "text_en",
            "text_vi",
            "speaker_role",
        )

    def _validate_activity_template(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "activity_template",
            "template_key",
            "activity_kind",
            "input_contract",
            "grading_contract",
        )

    def _validate_assessment_criterion(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "assessment_criterion",
            "criterion_key",
            "objective_id",
            "observable_behavior",
        )

    def _validate_activity(
        self, payload: dict[str, Any], report: GateReport, revision_id: str | None
    ) -> None:
        self._require(
            payload,
            report,
            revision_id,
            "activity",
            "objective_id",
            "template_id",
            "assessment_criterion_id",
            "activity_kind",
            "prompt",
            "answer",
        )
        activity_kind = payload.get("activity_kind")
        choice_kinds = {"recognition", "listening"}
        open_kinds = {"controlled_production", "guided_speaking", "free_response"}
        if activity_kind not in choice_kinds | open_kinds:
            report.add(
                "activity.kind_invalid", "Activity kind is not supported", revision_id
            )
            return
        distractors = payload.get("distractors", [])
        if activity_kind in choice_kinds:
            is_valid = (
                isinstance(distractors, list)
                and len(distractors) == 3
                and len(set(distractors)) == 3
                and payload.get("answer") not in distractors
            )
            if not is_valid:
                report.add(
                    "activity.distractors_invalid",
                    "Recognition and listening need three distinct wrong distractors",
                    revision_id,
                )
        elif distractors:
            report.add(
                "activity.distractors_forbidden",
                "Production activities must not include distractors",
                revision_id,
            )

    def _validate_scenario_graph(
        self,
        scenario: dict[str, Any],
        revisions_by_id: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        report: GateReport,
    ) -> None:
        payload = scenario.get("payload", {})
        scenario_id = str(scenario.get("revision_id"))
        outgoing = [
            edge for edge in edges if edge.get("from_revision_id") == scenario_id
        ]
        if payload.get("practice_mode") == "branching":
            turn_ids = [
                str(edge.get("to_revision_id"))
                for edge in outgoing
                if edge.get("relation_type") == "scenario_turn"
                and revisions_by_id.get(str(edge.get("to_revision_id")), {}).get(
                    "content_type"
                )
                == "dialogue_turn"
            ]
            paths = [
                edge
                for edge in edges
                if str(edge.get("from_revision_id")) in turn_ids
                and edge.get("relation_type") == "response_path"
            ]
            valid_paths = [
                edge
                for edge in paths
                if edge.get("attributes", {}).get("learner_intent")
                and edge.get("attributes", {}).get("outcome")
            ]
            valid_path_counts = {
                turn_id: sum(
                    str(edge.get("from_revision_id")) == turn_id for edge in valid_paths
                )
                for turn_id in turn_ids
            }
            if not turn_ids or not any(
                count >= 2 for count in valid_path_counts.values()
            ):
                report.add(
                    "scenario.branch_missing",
                    "A branching scenario requires two semantic response paths",
                    scenario.get("revision_id"),
                )
            elif len(valid_paths) != len(paths):
                report.add(
                    "scenario.branch_semantics_missing",
                    "Each response path needs learner intent and outcome",
                    scenario.get("revision_id"),
                )
        elif payload.get("practice_mode") == "linear":
            turn_ids = {
                str(edge.get("to_revision_id"))
                for edge in outgoing
                if edge.get("relation_type") == "scenario_turn"
            }
            if any(
                edge.get("relation_type") == "response_path"
                and str(edge.get("from_revision_id")) in turn_ids | {scenario_id}
                and edge.get("attributes", {}).get("learner_choice")
                for edge in outgoing
                + [edge for edge in edges if edge.get("from_revision_id") in turn_ids]
            ):
                report.add(
                    "scenario.linear_branching_forbidden",
                    "Linear scenarios cannot expose learner-choice response paths",
                    scenario.get("revision_id"),
                )

    @staticmethod
    def _require(
        payload: dict[str, Any],
        report: GateReport,
        revision_id: str | None,
        content_type: str,
        *fields: str,
    ) -> None:
        for field_name in fields:
            if not payload.get(field_name):
                report.add(
                    f"{content_type}.{field_name}_missing",
                    f"{content_type} requires {field_name}",
                    revision_id,
                )

    @staticmethod
    def _minimum_score(value: Any, threshold: float) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= threshold
        )

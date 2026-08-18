from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    computed_field,
    field_validator,
    model_validator,
)


def _validate_json_value(value: Any, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite JSON numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} must contain only string keys")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a non-JSON value")


def canonical_json(value: Any) -> str:
    try:
        _validate_json_value(value)
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("payload must contain only JSON-compatible values") from exc


class ReviewState(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class CandidateState(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class EvidenceRole(StrEnum):
    DEFINITION = "definition"
    TRANSLATION = "translation"
    IPA = "ipa"
    EXAMPLE = "example"


class InputDispositionState(StrEnum):
    VALIDATED = "validated"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class ContentType(StrEnum):
    MODULE = "module"
    OBJECTIVE = "objective"
    LEXEME = "lexeme"
    SENSE = "sense"
    FORM = "form"
    CHUNK = "chunk"
    PATTERN = "pattern"
    SENTENCE = "sentence"
    AUDIO_ASSET = "audio_asset"
    SCENARIO = "scenario"
    DIALOGUE_TURN = "dialogue_turn"
    ACTIVITY_TEMPLATE = "activity_template"
    ASSESSMENT_CRITERION = "assessment_criterion"
    ACTIVITY = "activity"


class SourceAssetInput(BaseModel):
    model_config = ConfigDict(frozen=True, validate_assignment=True)

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    title: str = Field(min_length=1)
    locator: HttpUrl
    asset_version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_id: str
    license_url: HttpUrl
    attribution: str
    redistribution_allowed: bool
    validation_status: ReviewState = ReviewState.CANDIDATE

    @model_validator(mode="after")
    def approved_assets_have_rights_evidence(self) -> SourceAssetInput:
        if self.validation_status is ReviewState.APPROVED and (
            not self.redistribution_allowed
            or not self.license_id.strip()
            or not self.attribution.strip()
        ):
            raise ValueError(
                "license_id, attribution, and redistribution_allowed are required for approval"
            )
        return self


class SourceSnapshotInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    local_path: Path
    retrieved_at: datetime
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContentRevisionInput(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    content_type: ContentType
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def payload_must_not_be_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must not be empty")
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.payload).encode("utf-8")).hexdigest()


class LexicalDefinitionInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    raw_record_id: str = Field(min_length=1)
    source_word_id: int = Field(gt=0)
    source_definition_id: int = Field(gt=0)
    input_key: str = Field(min_length=1)
    source_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lemma: str = Field(min_length=1)
    pos: str = Field(min_length=1)
    frequency_rank: int = Field(ge=1)
    created_at: datetime


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1)
    input_id: str = Field(min_length=1)
    evidence_role: EvidenceRole
    source_row_id: int = Field(gt=0)
    source_name: str = Field(min_length=1)
    value: Any
    created_at: datetime

    @field_validator("value")
    @classmethod
    def value_must_be_json_compatible(cls, value: Any) -> Any:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def value_json(self) -> str:
        return canonical_json(self.value)

    @computed_field
    @property
    def value_sha256(self) -> str:
        return hashlib.sha256(self.value_json.encode("utf-8")).hexdigest()


class EvidenceRanking(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_run_id: str = Field(min_length=1)
    input_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    evidence_role: EvidenceRole
    rank: int = Field(ge=1)
    selected: bool
    eligible: bool
    reason: dict[str, Any]

    @field_validator("reason")
    @classmethod
    def reason_must_be_json_compatible(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def reason_json(self) -> str:
        return canonical_json(self.reason)


class InputDisposition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_run_id: str = Field(min_length=1)
    input_id: str = Field(min_length=1)
    state: InputDispositionState
    candidate_id: str | None = Field(default=None, min_length=1)
    failure_codes: list[str]
    rationale: dict[str, Any]
    updated_at: datetime

    @field_validator("failure_codes")
    @classmethod
    def failure_codes_must_be_json_compatible(cls, value: list[str]) -> list[str]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("rationale")
    @classmethod
    def rationale_must_be_json_compatible(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def failure_codes_json(self) -> str:
        return canonical_json(self.failure_codes)

    @computed_field
    @property
    def rationale_json(self) -> str:
        return canonical_json(self.rationale)


class RemediationAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: str = Field(min_length=1)
    validation_run_id: str = Field(min_length=1)
    input_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    selection: dict[str, Any]
    outcome: InputDispositionState
    failure_codes: list[str]
    rationale: dict[str, Any]
    created_at: datetime

    @field_validator("selection", "rationale")
    @classmethod
    def json_objects_must_be_json_compatible(
        cls, value: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("failure_codes")
    @classmethod
    def failure_codes_must_be_json_compatible(cls, value: list[str]) -> list[str]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def selection_json(self) -> str:
        return canonical_json(self.selection)

    @computed_field
    @property
    def failure_codes_json(self) -> str:
        return canonical_json(self.failure_codes)

    @computed_field
    @property
    def rationale_json(self) -> str:
        return canonical_json(self.rationale)


class RemediationRunReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    processed_count: int = Field(ge=0)
    validated_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    failure_counts: dict[str, int]
    completed_at: datetime | None = None

    @field_validator("failure_counts")
    @classmethod
    def failure_counts_must_be_json_compatible(
        cls, value: dict[str, int]
    ) -> dict[str, int]:
        try:
            _validate_json_value(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return value

    @computed_field
    @property
    def failure_counts_json(self) -> str:
        return canonical_json(self.failure_counts)

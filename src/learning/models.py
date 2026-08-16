from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
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


def canonical_json(value: dict[str, Any]) -> str:
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

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    content_type: ContentType
    payload: dict[str, Any]
    payload_sha256: str = ""

    @field_validator("payload")
    @classmethod
    def payload_must_not_be_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must not be empty")
        return value

    @model_validator(mode="after")
    def calculate_payload_hash(self) -> ContentRevisionInput:
        self.payload_sha256 = hashlib.sha256(
            canonical_json(self.payload).encode("utf-8")
        ).hexdigest()
        return self

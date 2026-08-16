import pytest
from pydantic import ValidationError

from src.learning.models import (
    ContentRevisionInput,
    ContentType,
    ReviewState,
    SourceAssetInput,
)


def test_source_asset_requires_license_and_attribution_for_approval():
    with pytest.raises(ValidationError, match="license_id"):
        SourceAssetInput(
            asset_id="test-source",
            title="Test source",
            locator="https://example.test/source",
            asset_version="2026-01",
            sha256="a" * 64,
            license_id="",
            license_url="https://example.test/license",
            attribution="",
            redistribution_allowed=True,
            validation_status="approved",
        )


def test_revision_input_has_deterministic_payload_hash():
    first = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": "Greet someone", "code": "A0.GREET"},
    )
    second = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"code": "A0.GREET", "outcome": "Greet someone"},
    )
    assert first.payload_sha256 == second.payload_sha256
    assert ReviewState.APPROVED.value == "approved"


def test_revision_payload_hash_tracks_nested_mutation_and_model_copy():
    revision = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": {"text": "Greet someone"}},
    )
    original_hash = revision.payload_sha256

    revision.payload["outcome"]["text"] = "Greet a neighbor"
    assert revision.payload_sha256 != original_hash

    copied = revision.model_copy(
        update={"payload": {"outcome": {"text": "Greet a colleague"}}}
    )
    assert copied.payload_sha256 != revision.payload_sha256


def test_revision_payload_hash_is_read_only():
    revision = ContentRevisionInput(
        stable_key="objective.greet",
        content_type=ContentType.OBJECTIVE,
        payload={"outcome": "Greet someone"},
    )

    with pytest.raises((AttributeError, TypeError, ValidationError)):
        revision.payload_sha256 = "0" * 64


def test_approved_source_rejects_blank_license_on_assignment():
    source = SourceAssetInput(
        asset_id="test-source",
        title="Test source",
        locator="https://example.test/source",
        asset_version="2026-01",
        sha256="a" * 64,
        license_id="CC-BY-4.0",
        license_url="https://example.test/license",
        attribution="Test author",
        redistribution_allowed=True,
        validation_status="approved",
    )

    with pytest.raises(ValidationError, match="license_id"):
        source.license_id = ""

    assert source.license_id == "CC-BY-4.0"
    assert source.attribution == "Test author"
    assert source.redistribution_allowed is True
    assert source.validation_status is ReviewState.APPROVED


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
        {"value": object()},
        {"value": {1: "non-string key"}},
        {"value": ("tuple is not JSON",)},
    ],
)
def test_revision_payload_accepts_only_finite_json_values(payload):
    with pytest.raises(ValidationError):
        ContentRevisionInput(
            stable_key="objective.greet",
            content_type=ContentType.OBJECTIVE,
            payload=payload,
        )

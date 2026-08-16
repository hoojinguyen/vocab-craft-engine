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

import hashlib
from pathlib import Path

import pytest

from src.learning.catalog import SourceCatalog
from src.learning.models import ReviewState, SourceAssetInput, canonical_json
from src.learning.store import LearningGraphStore


def _approved_source(asset_id: str = "approved-source") -> SourceAssetInput:
    return SourceAssetInput(
        asset_id=asset_id,
        title="Approved source",
        locator="https://example.test/sources/approved",
        asset_version="2026-08",
        sha256="a" * 64,
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Example author",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )


@pytest.fixture
def catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    return SourceCatalog(store)


def test_register_source_is_idempotent_and_preserves_input_attributes(
    catalog: SourceCatalog,
):
    source = _approved_source()

    catalog.register_source(source)
    catalog.register_source(
        source.model_copy(
            update={
                "title": "Replacement title",
                "attribution": "Replacement attribution",
                "validation_status": ReviewState.CANDIDATE,
            }
        )
    )

    assert (
        catalog.store.connection()
        .execute(
            """
        SELECT title, locator, asset_version, sha256, license_id, license_url,
               attribution, redistribution_allowed, validation_status
        FROM source_assets WHERE asset_id = ?
        """,
            [source.asset_id],
        )
        .fetchall()
        == [
            (
                source.title,
                str(source.locator),
                source.asset_version,
                source.sha256,
                source.license_id,
                str(source.license_url),
                source.attribution,
                True,
                ReviewState.APPROVED.value,
            )
        ]
    )


def test_register_source_rejects_changed_checksum(catalog: SourceCatalog):
    catalog.register_source(_approved_source())
    changed = _approved_source().model_copy(update={"sha256": "b" * 64})

    with pytest.raises(ValueError, match="checksum"):
        catalog.register_source(changed)

    assert (
        catalog.store.fetch_value(
            "SELECT sha256 FROM source_assets WHERE asset_id = ?", [changed.asset_id]
        )
        == "a" * 64
    )


@pytest.mark.parametrize(
    "asset_id, registered", [("missing-source", False), ("pending-source", True)]
)
def test_record_raw_snapshot_requires_an_approved_source(
    catalog: SourceCatalog, asset_id: str, registered: bool
):
    if registered:
        catalog.register_source(
            _approved_source(asset_id).model_copy(
                update={"validation_status": ReviewState.CANDIDATE}
            )
        )

    with pytest.raises(ValueError, match="approved"):
        catalog.record_raw_snapshot(asset_id, "word:hello", {"word": "hello"})

    assert catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 0


def test_record_raw_snapshot_is_idempotent_for_canonical_payload(
    catalog: SourceCatalog,
):
    source = _approved_source()
    catalog.register_source(source)

    first_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 1}
    )
    second_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"rank": 1, "word": "hello"}
    )
    expected_payload = canonical_json({"rank": 1, "word": "hello"})

    assert second_id == first_id
    assert (
        catalog.store.connection()
        .execute(
            """
        SELECT raw_record_id, payload_json, payload_sha256
        FROM raw_reference_records
        WHERE asset_id = ? AND external_key = ?
        """,
            [source.asset_id, "word:hello"],
        )
        .fetchall()
        == [
            (
                first_id,
                expected_payload,
                hashlib.sha256(expected_payload.encode("utf-8")).hexdigest(),
            )
        ]
    )


def test_record_raw_snapshot_retains_changed_payload_as_second_record(
    catalog: SourceCatalog,
):
    source = _approved_source()
    catalog.register_source(source)

    first_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 1}
    )
    second_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 2}
    )

    assert first_id != second_id
    rows = (
        catalog.store.connection()
        .execute(
            """
        SELECT raw_record_id, payload_sha256
        FROM raw_reference_records
        WHERE asset_id = ? AND external_key = ?
        ORDER BY payload_sha256
        """,
            [source.asset_id, "word:hello"],
        )
        .fetchall()
    )
    assert len(rows) == 2
    assert {row[0] for row in rows} == {first_id, second_id}
    assert {row[1] for row in rows} == {
        hashlib.sha256(
            canonical_json({"word": "hello", "rank": 1}).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            canonical_json({"word": "hello", "rank": 2}).encode("utf-8")
        ).hexdigest(),
    }

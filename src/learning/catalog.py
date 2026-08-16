from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from src.learning.models import ReviewState, SourceAssetInput, canonical_json
from src.learning.store import LearningGraphStore


class SourceCatalog:
    """Register immutable source assets and their raw reference snapshots."""

    def __init__(self, store: LearningGraphStore):
        self.store = store

    def register_source(self, source: SourceAssetInput) -> None:
        """Persist a source asset unless its asset ID has a conflicting checksum."""
        with self.store.transaction() as connection:
            existing_checksum = connection.execute(
                "SELECT sha256 FROM source_assets WHERE asset_id = ?",
                [source.asset_id],
            ).fetchone()
            if existing_checksum is not None:
                if existing_checksum[0] != source.sha256:
                    raise ValueError(
                        f"source asset {source.asset_id!r} is already registered "
                        "with a different checksum"
                    )
                return

            connection.execute(
                """
                INSERT INTO source_assets (
                    asset_id, title, locator, asset_version, sha256, license_id,
                    license_url, attribution, redistribution_allowed, validation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    source.asset_id,
                    source.title,
                    str(source.locator),
                    source.asset_version,
                    source.sha256,
                    source.license_id,
                    str(source.license_url),
                    source.attribution,
                    source.redistribution_allowed,
                    source.validation_status.value,
                ],
            )

    def record_raw_snapshot(
        self, asset_id: str, external_key: str, payload: dict[str, Any]
    ) -> str:
        """Store a content-addressed raw snapshot for an approved source asset."""
        payload_json = canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        with self.store.transaction() as connection:
            approved_source = connection.execute(
                """
                SELECT asset_id FROM source_assets
                WHERE asset_id = ? AND validation_status = ?
                """,
                [asset_id, ReviewState.APPROVED.value],
            ).fetchone()
            if approved_source is None:
                raise ValueError(
                    f"raw snapshots require an approved source asset: {asset_id!r}"
                )

            existing_snapshot = connection.execute(
                """
                SELECT raw_record_id FROM raw_reference_records
                WHERE asset_id = ? AND external_key = ? AND payload_sha256 = ?
                """,
                [asset_id, external_key, payload_sha256],
            ).fetchone()
            if existing_snapshot is not None:
                return str(existing_snapshot[0])

            raw_record_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO raw_reference_records (
                    raw_record_id, asset_id, external_key, record_type, payload_json,
                    payload_sha256, import_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    raw_record_id,
                    asset_id,
                    external_key,
                    "snapshot",
                    payload_json,
                    payload_sha256,
                    str(uuid4()),
                ],
            )
            return raw_record_id

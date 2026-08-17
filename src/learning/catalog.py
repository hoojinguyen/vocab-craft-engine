from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import duckdb

from src.learning.models import (
    ReviewState,
    SourceAssetInput,
    SourceSnapshotInput,
    canonical_json,
)
from src.learning.store import LearningGraphStore

_Result = TypeVar("_Result")
_WRITE_RETRY_ATTEMPTS = 4
_SOURCE_SNAPSHOT_HASH_CHUNK_SIZE = 64 * 1024


class _ConcurrentCatalogWrite(RuntimeError):
    pass


class SourceCatalog:
    """Register immutable source assets and their raw reference snapshots."""

    def __init__(self, store: LearningGraphStore):
        self.store = store

    def register_source(self, source: SourceAssetInput) -> None:
        """Persist a source asset unless its asset ID has a conflicting checksum."""
        self._retry_catalog_write(lambda: self._register_source_once(source))

    def _register_source_once(self, source: SourceAssetInput) -> None:
        with self.store.transaction() as connection:
            existing_checksum = connection.execute(
                "SELECT sha256 FROM source_assets WHERE asset_id = ?",
                [source.asset_id],
            ).fetchone()
            if existing_checksum is not None:
                self._ensure_matching_checksum(
                    source.asset_id, source.sha256, existing_checksum[0]
                )
                return

            connection.execute(
                """
                INSERT INTO source_assets (
                    asset_id, title, locator, asset_version, sha256, license_id,
                    license_url, attribution, redistribution_allowed, validation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
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
            stored_checksum = connection.execute(
                "SELECT sha256 FROM source_assets WHERE asset_id = ?",
                [source.asset_id],
            ).fetchone()
            if stored_checksum is None:
                raise _ConcurrentCatalogWrite
            self._ensure_matching_checksum(
                source.asset_id, source.sha256, stored_checksum[0]
            )

    def record_raw_snapshot(
        self, asset_id: str, external_key: str, payload: dict[str, Any]
    ) -> str:
        """Store a content-addressed raw snapshot for an approved source asset."""
        return self.append_raw_record(
            asset_id=asset_id,
            external_key=external_key,
            record_type="snapshot",
            payload=payload,
            import_run_id=str(uuid4()),
        )

    def record_source_snapshot(
        self, asset_id: str, local_path: Path, retrieved_at: datetime | str
    ) -> str:
        """Persist a local source file only when it matches its registered checksum."""
        path = Path(local_path)
        source_snapshot = SourceSnapshotInput(
            asset_id=asset_id,
            local_path=path,
            retrieved_at=retrieved_at,
            file_sha256=self._hash_file(path),
        )
        return self._retry_catalog_write(
            lambda: self._record_source_snapshot_once(source_snapshot)
        )

    def _record_source_snapshot_once(self, source_snapshot: SourceSnapshotInput) -> str:
        with self.store.transaction() as connection:
            stored_source = connection.execute(
                "SELECT sha256 FROM source_assets WHERE asset_id = ?",
                [source_snapshot.asset_id],
            ).fetchone()
            if stored_source is None:
                raise ValueError(
                    "source snapshots require a registered source asset: "
                    f"{source_snapshot.asset_id!r}"
                )
            self._ensure_matching_checksum(
                source_snapshot.asset_id,
                source_snapshot.file_sha256,
                str(stored_source[0]),
            )

            existing_snapshot = connection.execute(
                """
                SELECT snapshot_id FROM source_snapshots
                WHERE asset_id = ? AND file_sha256 = ?
                """,
                [source_snapshot.asset_id, source_snapshot.file_sha256],
            ).fetchone()
            if existing_snapshot is not None:
                return str(existing_snapshot[0])

            connection.execute(
                """
                INSERT INTO source_snapshots (
                    snapshot_id, asset_id, local_path, retrieved_at, file_sha256
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                [
                    str(uuid4()),
                    source_snapshot.asset_id,
                    str(source_snapshot.local_path),
                    self._duckdb_timestamp(source_snapshot.retrieved_at),
                    source_snapshot.file_sha256,
                ],
            )
            stored_snapshot = connection.execute(
                """
                SELECT snapshot_id FROM source_snapshots
                WHERE asset_id = ? AND file_sha256 = ?
                """,
                [source_snapshot.asset_id, source_snapshot.file_sha256],
            ).fetchone()
            if stored_snapshot is None:
                raise _ConcurrentCatalogWrite
            return str(stored_snapshot[0])

    def append_raw_record(
        self,
        asset_id: str,
        external_key: str,
        record_type: str,
        payload: dict[str, Any],
        import_run_id: str,
    ) -> str:
        """Append one approved-source record, retaining each changed payload version."""
        payload_json = canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        return self._retry_catalog_write(
            lambda: self._record_raw_snapshot_once(
                asset_id,
                external_key,
                record_type,
                payload_json,
                payload_sha256,
                import_run_id,
            )
        )

    def _record_raw_snapshot_once(
        self,
        asset_id: str,
        external_key: str,
        record_type: str,
        payload_json: str,
        payload_sha256: str,
        import_run_id: str,
    ) -> str:
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

            connection.execute(
                """
                INSERT INTO raw_reference_records (
                    raw_record_id, asset_id, external_key, record_type, payload_json,
                    payload_sha256, import_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                [
                    str(uuid4()),
                    asset_id,
                    external_key,
                    record_type,
                    payload_json,
                    payload_sha256,
                    import_run_id,
                ],
            )
            stored_snapshot = connection.execute(
                """
                SELECT raw_record_id FROM raw_reference_records
                WHERE asset_id = ? AND external_key = ? AND payload_sha256 = ?
                """,
                [asset_id, external_key, payload_sha256],
            ).fetchone()
            if stored_snapshot is None:
                raise _ConcurrentCatalogWrite
            return str(stored_snapshot[0])

    def _retry_catalog_write(self, operation: Callable[[], _Result]) -> _Result:
        last_error: Exception | None = None
        for attempt in range(_WRITE_RETRY_ATTEMPTS):
            try:
                return operation()
            except (
                _ConcurrentCatalogWrite,
                duckdb.TransactionException,
            ) as exc:
                last_error = exc
                if attempt + 1 < _WRITE_RETRY_ATTEMPTS:
                    time.sleep(0.01 * (attempt + 1))

        raise RuntimeError(
            "concurrent source catalog write did not settle"
        ) from last_error

    @staticmethod
    def _hash_file(local_path: Path) -> str:
        digest = hashlib.sha256()
        with local_path.open("rb") as source_file:
            while chunk := source_file.read(_SOURCE_SNAPSHOT_HASH_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _duckdb_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _ensure_matching_checksum(
        asset_id: str, submitted_checksum: str, stored_checksum: str
    ) -> None:
        if stored_checksum != submitted_checksum:
            raise ValueError(
                f"source asset {asset_id!r} is already registered with a different checksum"
            )

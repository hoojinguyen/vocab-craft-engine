from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, uuid4, uuid5

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
_RAW_RECORD_BATCH_SIZE = 250
_MAX_LEXICAL_FREQUENCY_RANK = 3500


def _positive_source_id(value: Any) -> int:
    try:
        source_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "lexical source identifiers must be positive integers"
        ) from exc
    if source_id <= 0:
        raise ValueError("lexical source identifiers must be positive integers")
    return source_id


def _frozen_lexical_frequency_rank(value: Any) -> int:
    try:
        frequency_rank = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("lexical frequency rank must be between 1 and 3500") from exc
    if not 1 <= frequency_rank <= _MAX_LEXICAL_FREQUENCY_RANK:
        raise ValueError("lexical frequency rank must be between 1 and 3500")
    return frequency_rank


def _lexical_evidence_payload(
    payload: dict[str, Any], word_id: int, definition_id: int
) -> list[dict[str, Any]]:
    """Normalize importer payload fields to catalog evidence rows."""
    definition = payload["definition"]
    definitions: list[dict[str, Any]] = [definition]
    definitions.extend(
        item for item in payload.get("definitions", []) if isinstance(item, dict)
    )
    definition_source_ids: set[int] = set()
    evidence: list[dict[str, Any]] = []
    for alternative in definitions:
        source_row_id = _positive_source_id(
            alternative.get("source_row_id", alternative.get("id", definition_id))
        )
        if source_row_id in definition_source_ids:
            continue
        definition_source_ids.add(source_row_id)
        evidence.append(
            {
                "evidence_role": "definition",
                "source_row_id": source_row_id,
                "source_name": alternative.get("source") or "sqlite-definitions",
                "value": alternative,
            }
        )
    for translation in payload.get("translations", []):
        if not isinstance(translation, dict):
            continue
        text = translation.get("text", translation.get("definition_vi"))
        if text is None:
            continue
        evidence.append(
            {
                "evidence_role": "translation",
                "source_row_id": translation.get("source_row_id", definition_id),
                "source_name": translation.get("source") or "sqlite-definitions",
                "value": translation,
            }
        )
    for field in ("ipa_uk", "ipa_us"):
        value = payload.get("word", {}).get(field)
        if value:
            evidence.append(
                {
                    "evidence_role": "ipa",
                    "source_row_id": word_id,
                    "source_name": payload.get("word", {}).get("source")
                    or "sqlite-words",
                    "value": {"kind": field, "value": value},
                }
            )
    if definition.get("example"):
        evidence.append(
            {
                "evidence_role": "example",
                "source_row_id": definition_id,
                "source_name": definition.get("source") or "sqlite-definitions",
                "value": {
                    "kind": "definition",
                    "text": definition.get("example"),
                    "definition_id": definition_id,
                },
            }
        )
    for example in payload.get("examples", []):
        if not isinstance(example, dict):
            continue
        sentence_id = example.get("source_row_id", example.get("id"))
        if example.get("text_en") is None or example.get("text_vi") is None:
            continue
        evidence.append(
            {
                "evidence_role": "example",
                "source_row_id": sentence_id,
                "source_name": example.get("source") or "sqlite-sentences",
                "value": example,
            }
        )
    return evidence


class _ConcurrentCatalogWrite(RuntimeError):
    pass


@dataclass(frozen=True)
class RawRecordInput:
    """One immutable request to append a raw reference record."""

    asset_id: str
    external_key: str
    record_type: str
    payload: dict[str, Any]
    import_run_id: str


@dataclass(frozen=True)
class SourceEvidenceLinkInput:
    """One immutable source example and its word-level linkage."""

    snapshot_id: str
    source_word_id: int
    source_row_id: int
    source_name: str
    source_table: str
    link_rank: int
    value: dict[str, Any]


class SourceCatalog:
    """Register immutable source assets and their raw reference snapshots."""

    def __init__(self, store: LearningGraphStore):
        self.store = store

    def register_source(self, source: SourceAssetInput) -> None:
        """Persist a source asset unless its asset ID has a conflicting checksum."""
        self._retry_catalog_write(lambda: self._register_source_once(source))

    def append_source_example_links(
        self, links: Sequence[SourceEvidenceLinkInput]
    ) -> list[str]:
        """Append snapshot-scoped example values and compact word links.

        Values use deterministic IDs so retries can safely create the link
        without looking up a generated identifier for every source sentence.
        """
        prepared: list[tuple[SourceEvidenceLinkInput, str, str, str]] = []
        for link in links:
            _positive_source_id(link.source_word_id)
            source_row_id = _positive_source_id(link.source_row_id)
            if not link.snapshot_id:
                raise ValueError("source evidence requires a snapshot ID")
            if not link.source_name.strip() or not link.source_table.strip():
                raise ValueError("source evidence requires source metadata")
            if int(link.link_rank) <= 0:
                raise ValueError("source evidence link rank must be positive")
            value_json = canonical_json(link.value)
            value_sha256 = hashlib.sha256(value_json.encode("utf-8")).hexdigest()
            source_evidence_id = str(
                uuid5(
                    NAMESPACE_URL,
                    ":".join(
                        (
                            link.snapshot_id,
                            "example",
                            link.source_table,
                            str(source_row_id),
                            value_sha256,
                        )
                    ),
                )
            )
            prepared.append((link, value_json, value_sha256, source_evidence_id))
        source_evidence_ids: list[str] = []
        for start in range(0, len(prepared), _RAW_RECORD_BATCH_SIZE):
            batch = prepared[start : start + _RAW_RECORD_BATCH_SIZE]
            source_evidence_ids.extend(
                self._retry_catalog_write(
                    lambda batch=batch: self._append_source_example_links_once(batch)
                )
            )
        return source_evidence_ids

    def _append_source_example_links_once(
        self,
        links: list[tuple[SourceEvidenceLinkInput, str, str, str]],
    ) -> list[str]:
        with self.store.transaction() as connection:
            snapshot_ids = {link.snapshot_id for link, _, _, _ in links}
            for snapshot_id in snapshot_ids:
                approved_snapshot = connection.execute(
                    """
                    SELECT 1
                    FROM source_snapshots AS snapshot
                    JOIN source_assets AS asset ON asset.asset_id = snapshot.asset_id
                    WHERE snapshot.snapshot_id = ? AND asset.validation_status = ?
                    """,
                    [snapshot_id, ReviewState.APPROVED.value],
                ).fetchone()
                if approved_snapshot is None:
                    raise ValueError(
                        "source evidence requires an approved source snapshot"
                    )
            for link, value_json, value_sha256, source_evidence_id in links:
                connection.execute(
                    """
                    INSERT INTO lexical_source_evidence (
                        source_evidence_id, snapshot_id, evidence_role, source_table,
                        source_row_id, source_name, value_json, value_sha256
                    ) VALUES (?, ?, 'example', ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        source_evidence_id,
                        link.snapshot_id,
                        link.source_table,
                        _positive_source_id(link.source_row_id),
                        link.source_name,
                        value_json,
                        value_sha256,
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO lexical_word_evidence_links (
                        snapshot_id, source_word_id, source_evidence_id, link_rank
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        link.snapshot_id,
                        _positive_source_id(link.source_word_id),
                        source_evidence_id,
                        int(link.link_rank),
                    ],
                )
        return [source_evidence_id for _, _, _, source_evidence_id in links]

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

    def record_immutable_raw_snapshot(
        self,
        asset_id: str,
        external_key: str,
        payload: dict[str, Any],
        record_type: str = "snapshot",
    ) -> str:
        """Record provenance once per source/key, retaining the first payload."""
        payload_json = canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        def write_once() -> str:
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
                        "raw snapshots require an approved source asset: "
                        f"{asset_id!r}"
                    )
                existing = connection.execute(
                    """
                    SELECT raw_record_id FROM raw_reference_records
                    WHERE asset_id = ? AND external_key = ?
                    """,
                    [asset_id, external_key],
                ).fetchone()
                if existing is not None:
                    return str(existing[0])
                raw_record_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO raw_reference_records (
                        raw_record_id, asset_id, external_key, record_type,
                        payload_json, payload_sha256, import_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        raw_record_id,
                        asset_id,
                        external_key,
                        record_type,
                        payload_json,
                        payload_sha256,
                        str(uuid4()),
                    ],
                )
                stored = connection.execute(
                    """
                    SELECT raw_record_id FROM raw_reference_records
                    WHERE asset_id = ? AND external_key = ?
                    """,
                    [asset_id, external_key],
                ).fetchone()
                if stored is None:
                    raise _ConcurrentCatalogWrite
                return str(stored[0])

        return self._retry_catalog_write(write_once)

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
        return self.append_raw_records(
            [
                RawRecordInput(
                    asset_id=asset_id,
                    external_key=external_key,
                    record_type=record_type,
                    payload=payload,
                    import_run_id=import_run_id,
                )
            ]
        )[0]

    def append_raw_records(self, records: Sequence[RawRecordInput]) -> list[str]:
        """Append raw records in bounded transactions with per-record idempotence."""
        prepared_records: list[tuple[RawRecordInput, str, str]] = []
        for record in records:
            payload_json = canonical_json(record.payload)
            prepared_records.append(
                (
                    record,
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                )
            )
        raw_record_ids: list[str] = []
        for start in range(0, len(prepared_records), _RAW_RECORD_BATCH_SIZE):
            batch = prepared_records[start : start + _RAW_RECORD_BATCH_SIZE]
            raw_record_ids.extend(
                self._retry_catalog_write(
                    lambda batch=batch: self._append_raw_records_once(batch)
                )
            )
        return raw_record_ids

    def append_lexical_definition_records(
        self, records: Sequence[RawRecordInput], snapshot_id: str
    ) -> list[str]:
        """Append ranked SQLite definition records and their evidence atomically.

        Raw records, their one-to-one lexical inputs, and evidence rows are written
        in the same bounded transaction.  The input key is the stable identity, so
        repeating an import returns the existing rows without creating duplicates.
        """
        prepared_records: list[tuple[RawRecordInput, str, str]] = []
        for record in records:
            payload_json = canonical_json(record.payload)
            prepared_records.append(
                (
                    record,
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                )
            )
        raw_record_ids: list[str] = []
        for start in range(0, len(prepared_records), _RAW_RECORD_BATCH_SIZE):
            batch = prepared_records[start : start + _RAW_RECORD_BATCH_SIZE]
            raw_record_ids.extend(
                self._retry_catalog_write(
                    lambda batch=batch: self._append_lexical_records_once(
                        batch, snapshot_id
                    )
                )
            )
        return raw_record_ids

    def append_lexical_definition_record(
        self, record: RawRecordInput, snapshot_id: str
    ) -> str:
        """Singular convenience wrapper for :meth:`append_lexical_definition_records`."""
        return self.append_lexical_definition_records([record], snapshot_id)[0]

    def _append_lexical_records_once(
        self,
        records: list[tuple[RawRecordInput, str, str]],
        snapshot_id: str,
    ) -> list[str]:
        with self.store.transaction() as connection:
            snapshot = connection.execute(
                "SELECT asset_id FROM source_snapshots WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchone()
            if snapshot is None:
                raise ValueError(f"source snapshot does not exist: {snapshot_id!r}")

            approved_asset_ids: set[str] = set()
            raw_record_ids: list[str] = []
            for record, payload_json, payload_sha256 in records:
                word = record.payload.get("word")
                definition = record.payload.get("definition")
                if not isinstance(word, dict) or not isinstance(definition, dict):
                    raise TypeError(
                        "lexical definition payload must contain word and definition"
                    )
                frequency_rank = _frozen_lexical_frequency_rank(
                    word.get("frequency_rank")
                )
                if record.asset_id not in approved_asset_ids:
                    approved_source = connection.execute(
                        """
                        SELECT asset_id FROM source_assets
                        WHERE asset_id = ? AND validation_status = ?
                        """,
                        [record.asset_id, ReviewState.APPROVED.value],
                    ).fetchone()
                    if approved_source is None:
                        raise ValueError(
                            "raw snapshots require an approved source asset: "
                            f"{record.asset_id!r}"
                        )
                    if str(snapshot[0]) != record.asset_id:
                        raise ValueError(
                            "lexical definition record asset does not match source snapshot"
                        )
                    approved_asset_ids.add(record.asset_id)

                existing_raw = connection.execute(
                    """
                    SELECT raw_record_id, payload_sha256
                    FROM raw_reference_records
                    WHERE asset_id = ? AND external_key = ?
                    """,
                    [record.asset_id, record.external_key],
                ).fetchone()
                if existing_raw is not None and str(existing_raw[1]) != payload_sha256:
                    raise ValueError(
                        "lexical definition external key has an immutable payload"
                    )
                if existing_raw is None:
                    raw_record_id = str(uuid4())
                    connection.execute(
                        """
                        INSERT INTO raw_reference_records (
                            raw_record_id, asset_id, external_key, record_type,
                            payload_json, payload_sha256, import_run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        [
                            raw_record_id,
                            record.asset_id,
                            record.external_key,
                            record.record_type,
                            payload_json,
                            payload_sha256,
                            record.import_run_id,
                        ],
                    )
                    stored_raw = connection.execute(
                        """
                        SELECT raw_record_id FROM raw_reference_records
                        WHERE asset_id = ? AND external_key = ? AND payload_sha256 = ?
                        """,
                        [record.asset_id, record.external_key, payload_sha256],
                    ).fetchone()
                    if stored_raw is None:
                        raise _ConcurrentCatalogWrite
                    raw_record_id = str(stored_raw[0])
                else:
                    raw_record_id = str(existing_raw[0])
                raw_record_ids.append(raw_record_id)

                word_id = _positive_source_id(
                    word.get(
                        "source_row_id", word.get("legacy_word_id", word.get("id"))
                    )
                )
                definition_id = _positive_source_id(
                    definition.get("source_row_id", definition.get("id"))
                )
                input_key = f"{record.asset_id}:{snapshot_id}:{record.external_key}"
                source_definition_sha256 = hashlib.sha256(
                    canonical_json(definition).encode("utf-8")
                ).hexdigest()
                existing_input = connection.execute(
                    """
                    SELECT input_id, raw_record_id, snapshot_id
                    FROM lexical_definition_inputs WHERE input_key = ?
                    """,
                    [input_key],
                ).fetchone()
                if existing_input is None:
                    input_id = str(uuid4())
                    connection.execute(
                        """
                        INSERT INTO lexical_definition_inputs (
                            input_id, snapshot_id, raw_record_id, source_word_id,
                            source_definition_id, input_key, source_definition_sha256,
                            lemma, pos, frequency_rank
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        [
                            input_id,
                            snapshot_id,
                            raw_record_id,
                            word_id,
                            definition_id,
                            input_key,
                            source_definition_sha256,
                            str(word.get("lemma", "")),
                            str(word.get("pos", "")),
                            frequency_rank,
                        ],
                    )
                    stored_input = connection.execute(
                        """
                        SELECT input_id, raw_record_id, snapshot_id
                        FROM lexical_definition_inputs WHERE input_key = ?
                        """,
                        [input_key],
                    ).fetchone()
                    if stored_input is None:
                        raise _ConcurrentCatalogWrite
                    existing_input = stored_input
                if (
                    str(existing_input[1]) != raw_record_id
                    or str(existing_input[2]) != snapshot_id
                ):
                    raise ValueError("lexical definition input identity has changed")
                input_id = str(existing_input[0])

                for evidence in _lexical_evidence_payload(
                    record.payload, word_id, definition_id
                ):
                    source_row_id = _positive_source_id(evidence.get("source_row_id"))
                    role = str(evidence.get("evidence_role", ""))
                    source_name = str(evidence.get("source_name") or "sqlite")
                    value = evidence.get("value")
                    value_json = canonical_json(value)
                    value_sha256 = hashlib.sha256(
                        value_json.encode("utf-8")
                    ).hexdigest()
                    connection.execute(
                        """
                        INSERT INTO lexical_evidence_items (
                            evidence_id, input_id, evidence_role, source_row_id,
                            source_name, value_json, value_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        [
                            str(uuid4()),
                            input_id,
                            role,
                            source_row_id,
                            source_name,
                            value_json,
                            value_sha256,
                        ],
                    )
            return raw_record_ids

    def _append_raw_records_once(
        self,
        records: list[tuple[RawRecordInput, str, str]],
    ) -> list[str]:
        with self.store.transaction() as connection:
            approved_asset_ids: set[str] = set()
            raw_record_ids: list[str] = []
            for record, payload_json, payload_sha256 in records:
                if record.asset_id not in approved_asset_ids:
                    approved_source = connection.execute(
                        """
                        SELECT asset_id FROM source_assets
                        WHERE asset_id = ? AND validation_status = ?
                        """,
                        [record.asset_id, ReviewState.APPROVED.value],
                    ).fetchone()
                    if approved_source is None:
                        raise ValueError(
                            "raw snapshots require an approved source asset: "
                            f"{record.asset_id!r}"
                        )
                    approved_asset_ids.add(record.asset_id)

                existing_snapshot = connection.execute(
                    """
                    SELECT raw_record_id FROM raw_reference_records
                    WHERE asset_id = ? AND external_key = ? AND payload_sha256 = ?
                    """,
                    [record.asset_id, record.external_key, payload_sha256],
                ).fetchone()
                if existing_snapshot is not None:
                    raw_record_ids.append(str(existing_snapshot[0]))
                    continue

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
                        record.asset_id,
                        record.external_key,
                        record.record_type,
                        payload_json,
                        payload_sha256,
                        record.import_run_id,
                    ],
                )
                stored_snapshot = connection.execute(
                    """
                    SELECT raw_record_id FROM raw_reference_records
                    WHERE asset_id = ? AND external_key = ? AND payload_sha256 = ?
                    """,
                    [record.asset_id, record.external_key, payload_sha256],
                ).fetchone()
                if stored_snapshot is None:
                    raise _ConcurrentCatalogWrite
                raw_record_ids.append(str(stored_snapshot[0]))
            return raw_record_ids

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

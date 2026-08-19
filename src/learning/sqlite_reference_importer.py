from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.learning.catalog import RawRecordInput, SourceCatalog, SourceEvidenceLinkInput
from src.learning.models import ReviewState, SourceAssetInput, canonical_json

FIRST_LEXICAL_POS = frozenset(
    {
        "noun",
        "verb",
        "adj",
        "adv",
        "prep",
        "pron",
        "det",
        "conj",
        "intj",
        "article",
        "num",
    }
)
FIRST_LEXICAL_LEMMA = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
MAX_FREQUENCY_RANK = 3500
MAX_EXAMPLES_PER_WORD = 3
IMPORT_BATCH_SIZE = 250
_HASH_CHUNK_SIZE = 64 * 1024
_MAX_SOURCE_ASSET_ID_FOR_MATERIALIZATION = 229
_MATERIALIZATION_CAPTURE_ATTEMPTS = 3
_SQLITE_ARTIFACT_SUFFIXES = ("", "-wal", "-shm", "-journal")


@dataclass(frozen=True)
class SQLiteReferenceMaterializationResult:
    """Immutable identity and paths produced by WAL-aware materialization."""

    source_snapshot_id: str
    original_asset_id: str
    materialized_path: Path
    materialized_sha256: str
    derived_asset_id: str
    snapshot_id: str
    provenance_raw_record_id: str

    @property
    def reference_path(self) -> Path:
        """Compatibility alias for callers that call the output a reference."""
        return self.materialized_path

    @property
    def output_path(self) -> Path:
        return self.materialized_path

    @property
    def materialized_asset_id(self) -> str:
        return self.derived_asset_id

    @property
    def materialized_snapshot_id(self) -> str:
        return self.snapshot_id


class SQLiteReferenceMaterializer:
    """Create a standalone SQLite backup while preserving a source WAL snapshot."""

    def __init__(self, catalog: SourceCatalog, output_root: Path | None = None) -> None:
        self.catalog = catalog
        if output_root is None:
            from config.settings import LEXICAL_53K_SNAPSHOT_DIR

            output_root = LEXICAL_53K_SNAPSHOT_DIR
        self.output_root = Path(output_root)

    @staticmethod
    def hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source_file:
            while chunk := source_file.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    _hash_file = hash_file

    def materialize(
        self,
        reference_path: Path,
        source_snapshot_id: str,
        retrieved_at: datetime | None = None,
        *,
        output_root: Path | None = None,
    ) -> SQLiteReferenceMaterializationResult:
        source_path = Path(reference_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        source_row = (
            self.catalog.store.connection()
            .execute(
                """
            SELECT snapshots.asset_id, snapshots.local_path, snapshots.file_sha256,
                   assets.title, assets.locator, assets.asset_version, assets.license_id,
                   assets.license_url, assets.attribution, assets.redistribution_allowed,
                   assets.validation_status
            FROM source_snapshots AS snapshots
            JOIN source_assets AS assets ON assets.asset_id = snapshots.asset_id
            WHERE snapshots.snapshot_id = ?
            """,
                [source_snapshot_id],
            )
            .fetchone()
        )
        if source_row is None:
            raise ValueError(f"source snapshot does not exist: {source_snapshot_id!r}")
        (
            original_asset_id,
            registered_path,
            registered_sha,
            title,
            locator,
            asset_version,
            license_id,
            license_url,
            attribution,
            redistribution_allowed,
            validation_status,
        ) = source_row
        if len(str(original_asset_id)) > _MAX_SOURCE_ASSET_ID_FOR_MATERIALIZATION:
            raise ValueError(
                "source asset ID is too long to create an exact materialized identity"
            )
        if Path(registered_path).resolve() != source_path.resolve():
            raise ValueError("source snapshot local path does not match reference path")
        if str(validation_status) != ReviewState.APPROVED.value:
            raise ValueError("source snapshot requires an approved source asset")
        if self.hash_file(source_path) != str(registered_sha):
            raise ValueError("source snapshot checksum does not match reference path")

        with tempfile.TemporaryDirectory(prefix="lexical-materialize-") as staging_dir:
            staged_dir = Path(staging_dir)
            staged_main = staged_dir / "reference.db"
            captured_before, captured_after = self._stage_consistent_source(
                source_path, staged_main, str(registered_sha)
            )
            materialized_tmp = staged_dir / "materialized.db"
            self._backup_sqlite(staged_main, materialized_tmp)
            materialized_sha = self.hash_file(materialized_tmp)

            output_dir = (
                Path(output_root) if output_root is not None else self.output_root
            ) / materialized_sha
            output_dir.mkdir(parents=True, exist_ok=True)
            materialized_path = output_dir / "reference.db"
            if materialized_path.exists():
                if self.hash_file(materialized_path) != materialized_sha:
                    raise ValueError(
                        "existing materialized snapshot has a different checksum"
                    )
            else:
                temporary_output = output_dir / f".reference.db.{uuid4().hex}.tmp"
                shutil.copyfile(materialized_tmp, temporary_output)
                if self.hash_file(temporary_output) != materialized_sha:
                    temporary_output.unlink(missing_ok=True)
                    raise ValueError("materialized snapshot changed while staging")
                os.replace(temporary_output, materialized_path)

            derived_asset_id = self._derived_asset_id(
                str(original_asset_id), materialized_sha
            )
            derived_source = SourceAssetInput(
                asset_id=derived_asset_id,
                title=f"{title} (materialized SQLite snapshot)",
                locator=str(locator),
                asset_version=f"{asset_version}+materialized.{materialized_sha[:12]}",
                sha256=materialized_sha,
                license_id=str(license_id),
                license_url=str(license_url),
                attribution=str(attribution),
                redistribution_allowed=bool(redistribution_allowed),
                validation_status=ReviewState.APPROVED,
            )
            self.catalog.register_source(derived_source)
            materialized_snapshot_id = self.catalog.record_source_snapshot(
                derived_asset_id,
                materialized_path,
                retrieved_at or datetime.now(UTC),
            )
            canonical_materialized_path = self._registered_snapshot_path(
                materialized_snapshot_id, derived_asset_id, materialized_sha
            )
            provenance = {
                "original_asset_id": str(original_asset_id),
                "original_snapshot_id": source_snapshot_id,
                "original_main_path": str(source_path),
                "original_main_sha256": captured_before[""],
                "original_wal_sha256": captured_before["-wal"],
                "original_shm_sha256": captured_before["-shm"],
                "original_journal_sha256": captured_before["-journal"],
                "original_artifact_hashes_before": captured_before,
                "original_artifact_hashes_after": captured_after,
                "materialized_asset_id": derived_asset_id,
                "materialized_sha256": materialized_sha,
                "materialized_snapshot_id": materialized_snapshot_id,
                "materialized_path": str(canonical_materialized_path),
            }
            provenance_raw_record_id = self.catalog.record_immutable_raw_snapshot(
                derived_asset_id,
                f"sqlite-materialization:{materialized_sha}",
                provenance,
                "sqlite_reference_materialization",
            )
        return SQLiteReferenceMaterializationResult(
            source_snapshot_id=source_snapshot_id,
            original_asset_id=str(original_asset_id),
            materialized_path=canonical_materialized_path,
            materialized_sha256=materialized_sha,
            derived_asset_id=derived_asset_id,
            snapshot_id=materialized_snapshot_id,
            provenance_raw_record_id=provenance_raw_record_id,
        )

    materialize_snapshot = materialize

    @staticmethod
    def _derived_asset_id(original_asset_id: str, materialized_sha: str) -> str:
        return f"{original_asset_id}.materialized.{materialized_sha[:12]}"

    def _registered_snapshot_path(
        self, snapshot_id: str, asset_id: str, file_sha256: str
    ) -> Path:
        snapshot = (
            self.catalog.store.connection()
            .execute(
                """
                SELECT asset_id, local_path, file_sha256
                FROM source_snapshots WHERE snapshot_id = ?
                """,
                [snapshot_id],
            )
            .fetchone()
        )
        if snapshot is None:
            raise RuntimeError("materialized source snapshot was not recorded")
        registered_asset_id, local_path, registered_sha256 = snapshot
        if (
            str(registered_asset_id) != asset_id
            or str(registered_sha256) != file_sha256
        ):
            raise RuntimeError("materialized source snapshot identity has changed")
        registered_path = Path(str(local_path))
        if not registered_path.is_file():
            raise ValueError("registered materialized snapshot path is unavailable")
        if self.hash_file(registered_path) != file_sha256:
            raise ValueError("registered materialized snapshot checksum has changed")
        return registered_path

    @classmethod
    def _stage_consistent_source(
        cls, source_path: Path, staged_main: Path, registered_sha: str
    ) -> tuple[dict[str, str | None], dict[str, str | None]]:
        for _ in range(_MATERIALIZATION_CAPTURE_ATTEMPTS):
            before = cls._artifact_hashes(source_path)
            if before[""] != registered_sha:
                raise ValueError(
                    "source snapshot checksum does not match reference path"
                )
            if before["-wal"] is not None and before["-journal"] is not None:
                raise ValueError("reference SQLite has conflicting journal sidecars")
            logical_sidecar = (
                "-wal"
                if before["-wal"] is not None
                else "-journal" if before["-journal"] is not None else None
            )
            cls._remove_staged_artifacts(staged_main)
            try:
                shutil.copyfile(source_path, staged_main)
                if logical_sidecar is not None:
                    shutil.copyfile(
                        Path(f"{source_path}{logical_sidecar}"),
                        Path(f"{staged_main}{logical_sidecar}"),
                    )
                after = cls._artifact_hashes(source_path)
            except OSError:
                cls._remove_staged_artifacts(staged_main)
                continue
            if before != after:
                cls._remove_staged_artifacts(staged_main)
                continue
            if cls.hash_file(staged_main) != before[""]:
                cls._remove_staged_artifacts(staged_main)
                continue
            if (
                logical_sidecar is not None
                and cls.hash_file(Path(f"{staged_main}{logical_sidecar}"))
                != before[logical_sidecar]
            ):
                cls._remove_staged_artifacts(staged_main)
                continue
            return before, after
        raise ValueError("source changed during materialization")

    @staticmethod
    def _artifact_hashes(source_path: Path) -> dict[str, str | None]:
        artifacts: dict[str, str | None] = {}
        for suffix in _SQLITE_ARTIFACT_SUFFIXES:
            artifact = Path(f"{source_path}{suffix}")
            artifacts[suffix] = (
                SQLiteReferenceMaterializer.hash_file(artifact)
                if artifact.exists()
                else None
            )
        return artifacts

    @staticmethod
    def _remove_staged_artifacts(staged_main: Path) -> None:
        for suffix in _SQLITE_ARTIFACT_SUFFIXES:
            Path(f"{staged_main}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _backup_sqlite(source_path: Path, destination: Path) -> None:
        source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(destination)
        try:
            source.execute("PRAGMA query_only = ON")
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()


@dataclass(frozen=True)
class SQLiteLexicalImportReport:
    """Outcome of one read-only lexical slice import."""

    source_snapshot_id: str
    import_run_id: str
    scanned_words: int
    eligible_words: int
    imported_or_existing_raw_records: int
    eligible_definitions: int | None = None
    source_example_links: int | None = None

    @property
    def imported_raw_records(self) -> int:
        """Compatibility name for records either newly inserted or already present."""
        return self.imported_or_existing_raw_records


class SQLiteLexicalReferenceImporter:
    """Read policy-eligible lexical bundles from an immutable SQLite reference."""

    def __init__(self, catalog: SourceCatalog) -> None:
        self.catalog = catalog

    def import_vertical_slice(
        self, reference_path: Path, snapshot_id: str, import_run_id: str
    ) -> SQLiteLexicalImportReport:
        source_path = Path(reference_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        asset_id, snapshot_sha256 = self._verify_source_snapshot(
            source_path, snapshot_id
        )

        self._assert_stable_source(source_path, snapshot_sha256)
        scanned_words = 0
        eligible_words = 0
        with tempfile.TemporaryDirectory(prefix="lexical-reference-") as staging_dir:
            staged_path = Path(staging_dir) / "reference.db"
            shutil.copyfile(source_path, staged_path)
            if self._hash_file(staged_path) != snapshot_sha256:
                raise ValueError("source snapshot changed while staging reference")

            with tempfile.SpooledTemporaryFile(
                max_size=8 * 1024 * 1024, mode="w+", encoding="utf-8"
            ) as spool:
                connection = sqlite3.connect(
                    f"{staged_path.resolve().as_uri()}?mode=ro", uri=True
                )
                try:
                    connection.execute("PRAGMA query_only = ON")
                    connection.execute("BEGIN")
                    cursor = connection.execute(
                        """
                        SELECT id, lemma, pos, frequency_rank, cefr_level, ipa_uk, ipa_us, source
                        FROM words
                        WHERE frequency_rank >= 1 AND frequency_rank <= ?
                        ORDER BY frequency_rank, id
                        """,
                        [MAX_FREQUENCY_RANK],
                    )
                    while words := cursor.fetchmany(IMPORT_BATCH_SIZE):
                        scanned_words += len(words)
                        for word in words:
                            if not self._is_eligible(word[1], word[2]):
                                continue
                            record = self._raw_record_for_word(
                                connection, asset_id, word, import_run_id
                            )
                            spool.write(
                                json.dumps(record.__dict__, ensure_ascii=False) + "\n"
                            )
                            eligible_words += 1
                    connection.rollback()
                finally:
                    connection.close()

                self._assert_stable_source(source_path, snapshot_sha256)
                spool.seek(0)
                batch: list[RawRecordInput] = []
                for line in spool:
                    values = json.loads(line)
                    batch.append(RawRecordInput(**values))
                    if len(batch) == IMPORT_BATCH_SIZE:
                        self.catalog.append_raw_records(batch)
                        batch = []
                if batch:
                    self.catalog.append_raw_records(batch)
        return SQLiteLexicalImportReport(
            source_snapshot_id=snapshot_id,
            import_run_id=import_run_id,
            scanned_words=scanned_words,
            eligible_words=eligible_words,
            imported_or_existing_raw_records=eligible_words,
        )

    def import_ranked_definitions(
        self, reference_path: Path, snapshot_id: str, import_run_id: str
    ) -> SQLiteLexicalImportReport:
        """Stream one immutable raw record for every eligible source definition."""
        source_path = Path(reference_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        asset_id, snapshot_sha256 = self._verify_materialized_snapshot(
            source_path, snapshot_id
        )
        scanned_words = 0
        eligible_words = 0
        eligible_definitions = 0
        source_example_links = 0
        previous_word_id: int | None = None
        previous_eligible_word_id: int | None = None
        with tempfile.TemporaryDirectory(
            prefix="lexical-ranked-reference-"
        ) as staging_dir:
            staged_path = Path(staging_dir) / "reference.db"
            self._stage_verified_snapshot(source_path, staged_path, snapshot_sha256)
            connection = sqlite3.connect(
                f"{staged_path.resolve().as_uri()}?mode=ro", uri=True
            )
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                source_example_links = self._import_source_example_links(
                    connection, snapshot_id
                )
                cursor = connection.execute(
                    """
                    SELECT
                        words.id, words.lemma, words.pos, words.frequency_rank,
                        words.cefr_level, words.ipa_uk, words.ipa_us, words.source,
                        definitions.id, definitions.definition_en,
                        definitions.definition_vi, definitions.example, definitions.source
                    FROM words
                    LEFT JOIN definitions ON definitions.word_id = words.id
                    WHERE words.frequency_rank >= 1
                      AND words.frequency_rank <= ?
                    ORDER BY words.frequency_rank, words.id, definitions.id
                    """,
                    [MAX_FREQUENCY_RANK],
                )
                batch: list[RawRecordInput] = []
                while rows := cursor.fetchmany(IMPORT_BATCH_SIZE):
                    for row in rows:
                        word_id = int(row[0])
                        if word_id != previous_word_id:
                            scanned_words += 1
                            previous_word_id = word_id
                        if word_id != previous_eligible_word_id:
                            eligible_words += 1
                            previous_eligible_word_id = word_id
                        if row[8] is None:
                            continue
                        batch.append(
                            self._raw_record_for_definition(
                                connection, asset_id, row, import_run_id
                            )
                        )
                        eligible_definitions += 1
                        if len(batch) == IMPORT_BATCH_SIZE:
                            self.catalog.append_lexical_definition_records(
                                batch, snapshot_id
                            )
                            batch = []
                if batch:
                    self.catalog.append_lexical_definition_records(batch, snapshot_id)
                connection.rollback()
            finally:
                connection.close()

        return SQLiteLexicalImportReport(
            source_snapshot_id=snapshot_id,
            import_run_id=import_run_id,
            scanned_words=scanned_words,
            eligible_words=eligible_words,
            imported_or_existing_raw_records=eligible_definitions,
            eligible_definitions=eligible_definitions,
            source_example_links=source_example_links,
        )

    def _import_source_example_links(
        self, connection: sqlite3.Connection, snapshot_id: str
    ) -> int:
        """Persist each linked bilingual source sentence once per source word."""
        word_sentence_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(word_sentences)")
        }
        if "rank" in word_sentence_columns:
            link_rank_expression = "word_sentences.rank"
            order_expression = "word_sentences.rank"
        else:
            # Some production snapshots predate the rank column.  Derive a
            # stable rank from sentence ID rather than inventing an arbitrary
            # insertion-order dependency.
            link_rank_expression = (
                "ROW_NUMBER() OVER (PARTITION BY word_sentences.word_id "
                "ORDER BY word_sentences.sentence_id)"
            )
            order_expression = "word_sentences.sentence_id"
        cursor = connection.execute(
            f"""
            SELECT word_sentences.word_id, sentences.id, {link_rank_expression},
                   sentences.text_en, sentences.text_vi, sentences.source
            FROM word_sentences
            JOIN words ON words.id = word_sentences.word_id
            JOIN sentences ON sentences.id = word_sentences.sentence_id
            WHERE words.frequency_rank BETWEEN 1 AND ?
              AND sentences.text_en IS NOT NULL
              AND sentences.text_vi IS NOT NULL
            ORDER BY words.frequency_rank, word_sentences.word_id,
                     {order_expression}, sentences.id
            """,
            [MAX_FREQUENCY_RANK],
        )
        total = 0
        while rows := cursor.fetchmany(IMPORT_BATCH_SIZE):
            links = [
                SourceEvidenceLinkInput(
                    snapshot_id=snapshot_id,
                    source_word_id=int(word_id),
                    source_row_id=int(sentence_id),
                    source_name=str(source_name or "sqlite-sentences"),
                    source_table="sentences",
                    link_rank=int(link_rank),
                    value={
                        "kind": "linked",
                        "sentence_id": int(sentence_id),
                        "text_en": text_en,
                        "text_vi": text_vi,
                        "source": source_name,
                    },
                )
                for word_id, sentence_id, link_rank, text_en, text_vi, source_name in rows
            ]
            self.catalog.append_source_example_links(links)
            total += len(links)
        return total

    @staticmethod
    def _stage_verified_snapshot(
        source_path: Path, staged_path: Path, snapshot_sha256: str
    ) -> None:
        shutil.copyfile(source_path, staged_path)
        if SQLiteLexicalReferenceImporter._hash_file(staged_path) != snapshot_sha256:
            raise ValueError("source snapshot changed while staging reference")

    def _verify_materialized_snapshot(
        self, source_path: Path, snapshot_id: str
    ) -> tuple[str, str]:
        snapshot = (
            self.catalog.store.connection()
            .execute(
                """
            SELECT asset_id, local_path, file_sha256
            FROM source_snapshots WHERE snapshot_id = ?
            """,
                [snapshot_id],
            )
            .fetchone()
        )
        if snapshot is None:
            raise ValueError(f"source snapshot does not exist: {snapshot_id!r}")
        asset_id, snapshot_path, snapshot_sha256 = snapshot
        if Path(snapshot_path).resolve() != source_path.resolve():
            raise ValueError("source snapshot local path does not match reference path")
        expected_suffix = f".materialized.{str(snapshot_sha256)[:12]}"
        if not str(asset_id).endswith(expected_suffix):
            raise ValueError(
                "ranked definition imports require a materialized snapshot"
            )
        approved = (
            self.catalog.store.connection()
            .execute(
                """
            SELECT 1 FROM source_assets
            WHERE asset_id = ? AND validation_status = ?
            """,
                [asset_id, ReviewState.APPROVED.value],
            )
            .fetchone()
        )
        if approved is None:
            raise ValueError("source snapshot requires an approved source asset")
        if any(
            Path(f"{source_path}{suffix}").exists()
            for suffix in ("-wal", "-shm", "-journal")
        ):
            raise ValueError("materialized reference has volatile sidecar files")
        if self._hash_file(source_path) != str(snapshot_sha256):
            raise ValueError("source snapshot checksum does not match reference path")
        self._require_materialization_provenance(
            str(asset_id),
            snapshot_id,
            Path(snapshot_path),
            str(snapshot_sha256),
        )
        return str(asset_id), str(snapshot_sha256)

    def _require_materialization_provenance(
        self,
        asset_id: str,
        snapshot_id: str,
        snapshot_path: Path,
        snapshot_sha256: str,
    ) -> None:
        provenance = (
            self.catalog.store.connection()
            .execute(
                """
                SELECT record_type, payload_json, payload_sha256
                FROM raw_reference_records
                WHERE asset_id = ? AND external_key = ?
                """,
                [asset_id, f"sqlite-materialization:{snapshot_sha256}"],
            )
            .fetchone()
        )
        if (
            provenance is None
            or str(provenance[0]) != "sqlite_reference_materialization"
        ):
            raise ValueError(
                "ranked definition imports require materialization provenance"
            )
        try:
            payload = json.loads(str(provenance[1]))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ranked definition imports require valid materialization provenance"
            ) from exc
        if not isinstance(payload, dict):
            raise TypeError(
                "ranked definition imports require valid materialization provenance"
            )
        payload_sha256 = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        if payload_sha256 != str(provenance[2]):
            raise ValueError(
                "ranked definition imports require valid materialization provenance"
            )
        if (
            payload.get("materialized_asset_id") != asset_id
            or payload.get("materialized_sha256") != snapshot_sha256
            or payload.get("materialized_snapshot_id") != snapshot_id
        ):
            raise ValueError(
                "ranked definition imports require matching materialization provenance"
            )
        materialized_path = payload.get("materialized_path")
        if not isinstance(materialized_path, str) or (
            Path(materialized_path).resolve() != snapshot_path.resolve()
        ):
            raise ValueError(
                "ranked definition imports require matching materialization provenance"
            )
        original_asset_id = payload.get("original_asset_id")
        original_snapshot_id = payload.get("original_snapshot_id")
        original_main_path = payload.get("original_main_path")
        original_main_sha256 = payload.get("original_main_sha256")
        if not all(
            isinstance(value, str) and value
            for value in (
                original_asset_id,
                original_snapshot_id,
                original_main_path,
                original_main_sha256,
            )
        ):
            raise ValueError(
                "ranked definition imports require complete materialization provenance"
            )
        original_snapshot = (
            self.catalog.store.connection()
            .execute(
                """
                SELECT asset_id, local_path, file_sha256
                FROM source_snapshots WHERE snapshot_id = ?
                """,
                [original_snapshot_id],
            )
            .fetchone()
        )
        if original_snapshot is None:
            raise ValueError(
                "ranked definition imports require complete materialization provenance"
            )
        registered_original_asset, registered_original_path, registered_original_sha = (
            original_snapshot
        )
        if (
            str(registered_original_asset) != original_asset_id
            or str(registered_original_sha) != original_main_sha256
            or Path(str(registered_original_path)).resolve()
            != Path(original_main_path).resolve()
        ):
            raise ValueError(
                "ranked definition imports require matching materialization provenance"
            )

    @classmethod
    def _raw_record_for_definition(
        cls,
        connection: sqlite3.Connection,
        asset_id: str,
        row: tuple[Any, ...],
        import_run_id: str,
    ) -> RawRecordInput:
        (
            word_id,
            lemma,
            pos,
            frequency_rank,
            cefr_level,
            ipa_uk,
            ipa_us,
            word_source,
            definition_id,
            definition_en,
            definition_vi,
            definition_example,
            definition_source,
        ) = row
        definitions = [
            {
                "id": int(source_definition_id),
                "definition_id": int(source_definition_id),
                "source_row_id": int(source_definition_id),
                "source_table": "definitions",
                "definition_en": source_definition_en,
                "definition_vi": source_definition_vi,
                "example": source_example,
                "source": source_definition_source,
            }
            for (
                source_definition_id,
                source_definition_en,
                source_definition_vi,
                source_example,
                source_definition_source,
            ) in connection.execute(
                """
                SELECT id, definition_en, definition_vi, example, source
                FROM definitions WHERE word_id = ? ORDER BY id
                """,
                [word_id],
            ).fetchall()
        ]
        translations = [
            {
                "source_row_id": item["source_row_id"],
                "source_table": "definitions",
                "definition_id": item["definition_id"],
                "text": item["definition_vi"],
                "source": item["source"],
            }
            for item in definitions
            if item["definition_vi"] is not None
        ]
        word = {
            "id": int(word_id),
            "word_id": int(word_id),
            "legacy_word_id": int(word_id),
            "source_row_id": int(word_id),
            "source_table": "words",
            "lemma": str(lemma).strip().lower(),
            "pos": str(pos).strip().lower(),
            "frequency_rank": int(frequency_rank),
            "cefr_level": cefr_level,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "source": word_source,
        }
        definition = {
            "id": int(definition_id),
            "definition_id": int(definition_id),
            "source_row_id": int(definition_id),
            "source_table": "definitions",
            "word_id": int(word_id),
            "definition_en": definition_en,
            "definition_vi": definition_vi,
            "example": definition_example,
            "source": definition_source,
        }
        payload = {
            "word": word,
            "definition": definition,
            "definitions": definitions,
            "translations": translations,
            "examples": [],
            "source_tables": {
                "words": {"source_row_id": int(word_id)},
                "definitions": [item["source_row_id"] for item in definitions],
                "linked_example_scope": {"source_word_id": int(word_id)},
            },
            "source_ids": {
                "words": [int(word_id)],
                "definitions": [item["source_row_id"] for item in definitions],
                "linked_example_word_id": int(word_id),
            },
        }
        return RawRecordInput(
            asset_id=asset_id,
            external_key=f"sqlite-lexical-definition:{word_id}:{definition_id}",
            record_type="sqlite_lexical_definition_evidence",
            payload=payload,
            import_run_id=import_run_id,
        )

    def _verify_source_snapshot(
        self, source_path: Path, snapshot_id: str
    ) -> tuple[str, str]:
        snapshot = (
            self.catalog.store.connection()
            .execute(
                """
            SELECT asset_id, local_path, file_sha256
            FROM source_snapshots
            WHERE snapshot_id = ?
            """,
                [snapshot_id],
            )
            .fetchone()
        )
        if snapshot is None:
            raise ValueError(f"source snapshot does not exist: {snapshot_id!r}")

        asset_id, snapshot_path, snapshot_sha256 = snapshot
        if Path(snapshot_path).resolve() != source_path.resolve():
            raise ValueError("source snapshot local path does not match reference path")
        self._assert_stable_source(source_path, snapshot_sha256)
        return str(asset_id), str(snapshot_sha256)

    @staticmethod
    def _assert_stable_source(source_path: Path, snapshot_sha256: str) -> None:
        sidecars = tuple(
            Path(f"{source_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")
        )
        if any(sidecar.exists() for sidecar in sidecars):
            raise ValueError("reference SQLite has volatile sidecar files")
        if SQLiteLexicalReferenceImporter._hash_file(source_path) != snapshot_sha256:
            raise ValueError("source snapshot checksum does not match reference path")

    @staticmethod
    def _is_eligible(lemma: object, pos: object) -> bool:
        if not isinstance(lemma, str) or not isinstance(pos, str):
            return False
        return (
            pos.strip().lower() in FIRST_LEXICAL_POS
            and FIRST_LEXICAL_LEMMA.fullmatch(lemma.strip().lower()) is not None
        )

    @classmethod
    def _raw_record_for_word(
        cls,
        connection: sqlite3.Connection,
        asset_id: str,
        word: tuple[Any, ...],
        import_run_id: str,
    ) -> RawRecordInput:
        (
            word_id,
            lemma,
            pos,
            frequency_rank,
            cefr_level,
            ipa_uk,
            ipa_us,
            source,
        ) = word
        definitions = [
            {
                "definition_en": definition_en,
                "definition_vi": definition_vi,
                "example": example,
                "source": definition_source,
            }
            for definition_en, definition_vi, example, definition_source in connection.execute(
                """
                SELECT definition_en, definition_vi, example, source
                FROM definitions
                WHERE word_id = ?
                ORDER BY id
                """,
                [word_id],
            ).fetchall()
        ]
        examples = [
            {"text_en": text_en, "text_vi": text_vi, "source": sentence_source}
            for text_en, text_vi, sentence_source in connection.execute(
                """
                SELECT sentences.text_en, sentences.text_vi, sentences.source
                FROM word_sentences
                JOIN sentences ON sentences.id = word_sentences.sentence_id
                WHERE word_sentences.word_id = ?
                  AND sentences.text_en IS NOT NULL
                  AND sentences.text_vi IS NOT NULL
                ORDER BY word_sentences.sentence_id
                LIMIT ?
                """,
                [word_id, MAX_EXAMPLES_PER_WORD],
            ).fetchall()
        ]
        normalized_lemma = lemma.strip().lower()
        normalized_pos = pos.strip().lower()
        return RawRecordInput(
            asset_id=asset_id,
            external_key=f"sqlite-lexical:{word_id}",
            record_type="sqlite_lexical_bundle",
            payload={
                "word": {
                    "legacy_word_id": word_id,
                    "lemma": normalized_lemma,
                    "pos": normalized_pos,
                    "frequency_rank": frequency_rank,
                    "cefr_level": cefr_level,
                    "ipa_uk": ipa_uk,
                    "ipa_us": ipa_us,
                    "source": source,
                },
                "definitions": definitions,
                "examples": examples,
            },
            import_run_id=import_run_id,
        )

    @staticmethod
    def _hash_file(source_path: Path) -> str:
        digest = hashlib.sha256()
        with source_path.open("rb") as source_file:
            while chunk := source_file.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

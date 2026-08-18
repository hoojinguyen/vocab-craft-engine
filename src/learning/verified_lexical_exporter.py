"""Atomic exporter for the complete verified lexical SQLite release."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.learning.lexical_reporting import QuarantineExporter
from src.learning.models import canonical_json
from src.learning.store import LearningGraphStore
from src.learning.verified_lexical_pack import VerifiedLexicalPack

_DATABASE_NAME = "english_dataset_verified_v1.db"
_QUARANTINE_NAME = "quarantine_v1.db"

_SCHEMA = """
CREATE TABLE senses (
    sense_id TEXT PRIMARY KEY,
    stable_key TEXT NOT NULL UNIQUE,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL,
    definition_en TEXT NOT NULL,
    definition_vi TEXT NOT NULL,
    ipa_uk TEXT,
    ipa_us TEXT,
    frequency_rank INTEGER NOT NULL,
    cefr_level TEXT NOT NULL
);
CREATE TABLE sense_examples (
    sense_id TEXT NOT NULL REFERENCES senses(sense_id),
    rank INTEGER NOT NULL,
    text_en TEXT NOT NULL,
    text_vi TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(sense_id, rank)
);
CREATE TABLE sense_provenance (
    sense_id TEXT NOT NULL REFERENCES senses(sense_id),
    snapshot_id TEXT NOT NULL,
    raw_record_id TEXT NOT NULL,
    source_word_id INTEGER NOT NULL,
    source_definition_id INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(sense_id, raw_record_id)
);
CREATE TABLE release_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX idx_senses_lemma_pos ON senses(lemma, pos);
CREATE INDEX idx_senses_rank ON senses(frequency_rank);
CREATE INDEX idx_senses_cefr ON senses(cefr_level);
CREATE INDEX idx_sense_examples_lookup ON sense_examples(sense_id, rank);
CREATE INDEX idx_sense_provenance_lookup ON sense_provenance(sense_id, raw_record_id);
"""


@dataclass(frozen=True)
class VerifiedLexicalExportResult:
    output_dir: Path
    sqlite_path: Path
    manifest_path: Path
    sha256_path: Path
    quarantine_path: Path
    quarantine_sha256_path: Path


class VerifiedLexicalPackExporter:
    """Publish a verified release only after all staged files pass checks."""

    def __init__(self, store: LearningGraphStore) -> None:
        self.store = store

    def export(
        self, pack: VerifiedLexicalPack, output_dir: Path
    ) -> VerifiedLexicalExportResult:
        destination = Path(output_dir)
        if destination.exists():
            raise FileExistsError(destination)
        self._require_unpublished_version(pack.version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{_DATABASE_NAME}.", dir=destination.parent)
        )
        try:
            sqlite_path = staging / _DATABASE_NAME
            self._write_database(sqlite_path, pack)
            self._verify_sqlite(sqlite_path)
            quarantine_result = QuarantineExporter(self.store).export(
                pack.validation_run_id, staging
            )
            self._verify_sqlite(quarantine_result.database_path)
            checksum_path = staging / f"{_DATABASE_NAME}.sha256"
            checksum_path.write_text(
                f"{self._sha256(sqlite_path)}  {_DATABASE_NAME}\n", encoding="utf-8"
            )
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(
                self._manifest_json(pack, sqlite_path, quarantine_result.database_path),
                encoding="utf-8",
            )
            self._verify_checksum(sqlite_path, checksum_path)
            self._fsync_files(
                (
                    sqlite_path,
                    quarantine_result.database_path,
                    quarantine_result.checksum_path,
                    checksum_path,
                    manifest_path,
                )
            )
            self._fsync_directory(staging)
            os.replace(staging, destination)
            self._fsync_directory(destination.parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        result = VerifiedLexicalExportResult(
            output_dir=destination,
            sqlite_path=destination / _DATABASE_NAME,
            manifest_path=destination / "manifest.json",
            sha256_path=destination / f"{_DATABASE_NAME}.sha256",
            quarantine_path=destination / _QUARANTINE_NAME,
            quarantine_sha256_path=destination / f"{_QUARANTINE_NAME}.sha256",
        )
        self._record_release_build(pack, result)
        return result

    def _require_unpublished_version(self, version: str) -> None:
        existing = self.store.fetch_value(
            "SELECT release_build_id FROM lexical_release_builds WHERE release_version = ?",
            [version],
        )
        if existing is not None:
            raise ValueError(
                f"verified lexical release version already exists: {version}"
            )

    def _write_database(self, path: Path, pack: VerifiedLexicalPack) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA)
            connection.executemany(
                """
                INSERT INTO senses (
                    sense_id, stable_key, lemma, pos, definition_en, definition_vi,
                    ipa_uk, ipa_us, frequency_rank, cefr_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sense["sense_id"],
                        sense["stable_key"],
                        sense["lemma"],
                        sense["pos"],
                        sense["definition_en"],
                        sense["definition_vi"],
                        sense["ipa_uk"],
                        sense["ipa_us"],
                        sense["frequency_rank"],
                        sense["cefr_level"],
                    )
                    for sense in pack.senses
                ],
            )
            connection.executemany(
                """
                INSERT INTO sense_examples (sense_id, rank, text_en, text_vi, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        example["sense_id"],
                        example["rank"],
                        example["text_en"],
                        example["text_vi"],
                        example["source"],
                    )
                    for example in pack.examples
                ],
            )
            connection.executemany(
                """
                INSERT INTO sense_provenance (
                    sense_id, snapshot_id, raw_record_id, source_word_id,
                    source_definition_id, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        provenance["sense_id"],
                        provenance["snapshot_id"],
                        provenance["raw_record_id"],
                        provenance["source_word_id"],
                        provenance["source_definition_id"],
                        canonical_json(provenance["evidence"]),
                    )
                    for provenance in pack.provenance
                ],
            )
            metadata = {
                "policy_version": pack.policy_version,
                "validation_run_id": pack.validation_run_id,
                "version": pack.version,
            }
            connection.executemany(
                "INSERT INTO release_metadata (key, value) VALUES (?, ?)",
                sorted(metadata.items()),
            )
            connection.commit()
        finally:
            connection.close()

    def _manifest_json(
        self, pack: VerifiedLexicalPack, sqlite_path: Path, quarantine_path: Path
    ) -> str:
        document = {
            "build_timestamp": datetime.now(UTC).isoformat(),
            "files": {
                _DATABASE_NAME: self._file_metadata(sqlite_path),
                _QUARANTINE_NAME: self._file_metadata(quarantine_path),
            },
            "policy_version": pack.policy_version,
            "reconciliation": pack.reconciliation,
            "source_attributions": list(pack.source_attributions),
            "source_snapshots": list(pack.source_snapshots),
            "validation_run_id": pack.validation_run_id,
            "version": pack.version,
        }
        return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @staticmethod
    def _verify_sqlite(path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"SQLite integrity_check failed for {path.name}")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError(f"SQLite foreign_key_check failed for {path.name}")
        finally:
            connection.close()

    @staticmethod
    def _verify_checksum(sqlite_path: Path, checksum_path: Path) -> None:
        expected = (
            f"{VerifiedLexicalPackExporter._sha256(sqlite_path)}  {sqlite_path.name}\n"
        )
        if checksum_path.read_text(encoding="utf-8") != expected:
            raise ValueError("verified lexical release checksum does not match SQLite")

    def _record_release_build(
        self, pack: VerifiedLexicalPack, result: VerifiedLexicalExportResult
    ) -> None:
        manifest_sha256 = self._sha256(result.manifest_path)
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT release_build_id FROM lexical_release_builds WHERE release_version = ?",
                [pack.version],
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"verified lexical release version already exists: {pack.version}"
                )
            connection.execute(
                """
                INSERT INTO lexical_release_builds (
                    release_build_id, validation_run_id, release_version,
                    manifest_sha256, counts_json, output_path
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid4()),
                    pack.validation_run_id,
                    pack.version,
                    manifest_sha256,
                    canonical_json(pack.reconciliation),
                    str(result.output_dir),
                ],
            )

    @staticmethod
    def _file_metadata(path: Path) -> dict[str, object]:
        return {
            "sha256": VerifiedLexicalPackExporter._sha256(path),
            "size_bytes": path.stat().st_size,
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65_536), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _fsync_files(paths: tuple[Path, ...]) -> None:
        for path in paths:
            with path.open("rb") as handle:
                os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

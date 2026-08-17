from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.learning.lexical_pack import LexicalPack

_SCHEMA = """
CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE senses (
    sense_id TEXT PRIMARY KEY,
    stable_key TEXT UNIQUE NOT NULL,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL,
    definition_en TEXT NOT NULL,
    definition_vi TEXT NOT NULL,
    frequency_rank INTEGER NOT NULL,
    cefr_level TEXT NOT NULL,
    ipa_uk TEXT,
    ipa_us TEXT,
    source_asset_id TEXT NOT NULL
);
CREATE TABLE sense_examples (
    sense_id TEXT NOT NULL REFERENCES senses(sense_id),
    rank INTEGER NOT NULL,
    text_en TEXT NOT NULL,
    text_vi TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(sense_id, rank)
);
CREATE INDEX idx_senses_lemma_pos ON senses(lemma, pos);
CREATE INDEX idx_senses_frequency ON senses(frequency_rank);
CREATE INDEX idx_examples_sense ON sense_examples(sense_id, rank);
"""


@dataclass(frozen=True)
class LexicalPackExportResult:
    output_dir: Path
    sqlite_path: Path
    json_path: Path
    manifest_path: Path
    sha256_path: Path


class LexicalPackExporter:
    """Publish an immutable relational lexical pack atomically."""

    def export(self, pack: LexicalPack, output_dir: Path) -> LexicalPackExportResult:
        destination = Path(output_dir)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(
            tempfile.mkdtemp(prefix=f".{pack.pack_id}-", dir=destination.parent)
        )
        try:
            sqlite_path = temporary_dir / "lexical.db"
            self._write_sqlite(sqlite_path, pack)
            self._verify_sqlite(sqlite_path)
            json_path = temporary_dir / "lexical.json"
            json_path.write_text(
                json.dumps(
                    {
                        "pack_id": pack.pack_id,
                        "version": pack.version,
                        "validation_run_id": pack.validation_run_id,
                        "cefr_level": pack.cefr_level,
                        "senses": list(pack.senses),
                        "examples": list(pack.examples),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            manifest = {
                "pack_id": pack.pack_id,
                "version": pack.version,
                "validation_run_id": pack.validation_run_id,
                "cefr_level": pack.cefr_level,
                "approved_sense_count": len(pack.senses),
                "quality_gates": pack.quality_report,
                "source_attributions": list(pack.source_attributions),
                "files": {
                    "lexical.db": self._file_metadata(sqlite_path),
                    "lexical.json": self._file_metadata(json_path),
                },
            }
            manifest_path = temporary_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            sha256_path = temporary_dir / "lexical.db.sha256"
            sha256_path.write_text(
                f"{self._sha256(sqlite_path)}  lexical.db\n", encoding="utf-8"
            )
            for file_path in (sqlite_path, json_path, manifest_path, sha256_path):
                with file_path.open("rb") as handle:
                    os.fsync(handle.fileno())
            temporary_dir.replace(destination)
        except BaseException:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise
        return LexicalPackExportResult(
            output_dir=destination,
            sqlite_path=destination / "lexical.db",
            json_path=destination / "lexical.json",
            manifest_path=destination / "manifest.json",
            sha256_path=destination / "lexical.db.sha256",
        )

    @staticmethod
    def _write_sqlite(path: Path, pack: LexicalPack) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA)
            connection.executemany(
                """
                INSERT INTO senses (
                    sense_id, stable_key, lemma, pos, definition_en, definition_vi,
                    frequency_rank, cefr_level, ipa_uk, ipa_us, source_asset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sense["sense_id"],
                        sense["stable_key"],
                        sense["lemma"],
                        sense["pos"],
                        sense["definition_en"],
                        sense["definition_vi"],
                        sense["frequency_rank"],
                        sense["cefr_level"],
                        sense["ipa_uk"],
                        sense["ipa_us"],
                        sense["source_asset_id"],
                    )
                    for sense in pack.senses
                ],
            )
            connection.executemany(
                "INSERT INTO sense_examples (sense_id, rank, text_en, text_vi, source) VALUES (?, ?, ?, ?, ?)",
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
            metadata = {
                "pack_id": pack.pack_id,
                "version": pack.version,
                "validation_run_id": pack.validation_run_id,
                "cefr_level": pack.cefr_level,
            }
            connection.executemany(
                "INSERT INTO pack_metadata (key, value) VALUES (?, ?)",
                sorted(metadata.items()),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _verify_sqlite(path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity_check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("SQLite foreign_key_check failed")
        finally:
            connection.close()

    @classmethod
    def _file_metadata(cls, path: Path) -> dict[str, object]:
        return {"sha256": cls._sha256(path), "size_bytes": path.stat().st_size}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65_536), b""):
                digest.update(block)
        return digest.hexdigest()

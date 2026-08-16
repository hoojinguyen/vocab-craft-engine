from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.composer import PackGraph
from src.learning.export_schema import CURRICULUM_PACK_SCHEMA
from src.learning.models import canonical_json


@dataclass(frozen=True)
class PackExportResult:
    output_dir: Path
    sqlite_path: Path
    json_path: Path
    manifest_path: Path
    sha256_path: Path


class CurriculumPackExporter:
    """Publish a quality-gated curriculum graph without overwriting a release."""

    def export(self, pack: PackGraph, output_dir: Path) -> PackExportResult:
        if not bool(pack.quality_report.get("passed")):
            raise ValueError("quality gates failed; pack cannot be published")
        destination = Path(output_dir)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(
            tempfile.mkdtemp(prefix=f".{pack.pack_id}-", dir=destination.parent)
        )
        try:
            sqlite_path = temporary_dir / "curriculum.db"
            self._write_sqlite(sqlite_path, pack)
            self._verify_sqlite(sqlite_path)
            json_path = temporary_dir / "curriculum.json"
            json_path.write_text(
                canonical_json(
                    {
                        "pack_id": pack.pack_id,
                        "version": pack.version,
                        "revisions": list(pack.revisions),
                        "edges": list(pack.edges),
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = self._write_manifest(
                temporary_dir, pack, [sqlite_path, json_path]
            )
            sha256_path = temporary_dir / "curriculum.db.sha256"
            sha256_path.write_text(
                f"{self._sha256(sqlite_path)}  curriculum.db\n", encoding="utf-8"
            )
            for file_path in (sqlite_path, json_path, manifest_path, sha256_path):
                with file_path.open("rb") as handle:
                    os.fsync(handle.fileno())
            temporary_dir.replace(destination)
        except BaseException:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise
        return PackExportResult(
            output_dir=destination,
            sqlite_path=destination / "curriculum.db",
            json_path=destination / "curriculum.json",
            manifest_path=destination / "manifest.json",
            sha256_path=destination / "curriculum.db.sha256",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65_536), b""):
                digest.update(block)
        return digest.hexdigest()

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

    def _write_sqlite(self, path: Path, pack: PackGraph) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(CURRICULUM_PACK_SCHEMA)
            connection.executemany(
                "INSERT INTO content_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["revision_id"],
                        item["content_id"],
                        item["stable_key"],
                        item["content_type"],
                        item["revision_number"],
                        item["payload_json"],
                        item["payload_sha256"],
                    )
                    for item in pack.revisions
                ],
            )
            connection.executemany(
                "INSERT INTO content_edges VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        edge["edge_id"],
                        edge["from_revision_id"],
                        edge["to_revision_id"],
                        edge["relation_type"],
                        edge["attributes_json"],
                    )
                    for edge in pack.edges
                ],
            )
            connection.executemany(
                "INSERT INTO source_attributions VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["asset_id"],
                        item["title"],
                        item["license_id"],
                        item["license_url"],
                        item["attribution"],
                        item["sha256"],
                    )
                    for item in pack.source_attributions
                ],
            )
            connection.execute(
                "INSERT INTO pack_metadata VALUES ('pack_id', ?)", [pack.pack_id]
            )
            connection.execute(
                "INSERT INTO pack_metadata VALUES ('version', ?)", [pack.version]
            )
            connection.execute(
                "INSERT INTO pack_metadata VALUES ('graph_schema_version', '1')"
            )
            connection.execute(
                "INSERT INTO quality_gate_results VALUES ('pack.quality', ?, ?, NULL)",
                [
                    int(bool(pack.quality_report["passed"])),
                    json.dumps(pack.quality_report, ensure_ascii=False, sort_keys=True),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _write_manifest(
        self, directory: Path, pack: PackGraph, files: list[Path]
    ) -> Path:
        file_entries = {
            path.name: {"sha256": self._sha256(path), "size_bytes": path.stat().st_size}
            for path in files
        }
        manifest: dict[str, Any] = {
            "pack_id": pack.pack_id,
            "version": pack.version,
            "graph_schema_version": 1,
            "revision_ids": list(pack.revision_ids),
            "source_attributions": list(pack.source_attributions),
            "quality_gates": pack.quality_report,
            "files": file_entries,
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return manifest_path

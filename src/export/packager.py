"""
Distribution Packager and Checksum Generator for SQLite Dataset.

Produces .zip archive, SHA256 checksum file, and metadata manifest.json.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import zipfile

logger = logging.getLogger(__name__)


class DatasetPackager:
    def compute_sha256(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def package(
        self,
        db_path: Path,
        output_dir: Path,
        version: str = "2.0.0",
        table_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Path]:
        db_file = Path(db_path)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not db_file.exists():
            raise FileNotFoundError(f"Database file not found: {db_file}")

        logger.info("Computing SHA256 checksum for %s...", db_file)
        sha256_hash = self.compute_sha256(db_file)

        # 1. Write .sha256 checksum file
        sha256_file = out_dir / f"{db_file.name}.sha256"
        sha256_file.write_text(f"{sha256_hash}  {db_file.name}\n", encoding="utf-8")

        # 2. Write manifest.json
        manifest_data: Dict[str, Any] = {
            "version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_file": db_file.name,
            "file_size_bytes": db_file.stat().st_size,
            "sha256": sha256_hash,
            "table_counts": table_counts or {},
        }
        manifest_file = out_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # 3. Create compressed .zip archive
        zip_file = out_dir / f"{db_file.stem}.zip"
        logger.info("Compressing dataset to %s...", zip_file)
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_file, arcname=db_file.name)
            zf.write(manifest_file, arcname="manifest.json")

        logger.info("Successfully created distribution package in %s", out_dir)
        return {
            "zip_path": zip_file,
            "sha256_path": sha256_file,
            "manifest_path": manifest_file,
        }

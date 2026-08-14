import json
import pytest
from pathlib import Path
from src.export.packager import DatasetPackager


def test_dataset_packager_creates_zip_and_checksum(tmp_path: Path):
    db_file = tmp_path / "english_dataset.db"
    db_file.write_bytes(b"SQLite format 3\x00dummy data for packaging test")

    output_dir = tmp_path / "dist"
    packager = DatasetPackager()
    result = packager.package(
        db_path=db_file,
        output_dir=output_dir,
        version="2.0.0",
        table_counts={"words": 5000, "sentences": 10000},
    )

    assert result["zip_path"].exists()
    assert result["sha256_path"].exists()
    assert result["manifest_path"].exists()

    # Verify sha256 checksum format
    sha_content = result["sha256_path"].read_text().strip()
    sha_hash = sha_content.split()[0]
    assert len(sha_hash) == 64

    # Verify manifest.json content
    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["version"] == "2.0.0"
    assert manifest["sha256"] == sha_hash
    assert manifest["table_counts"]["words"] == 5000
    assert manifest["file_size_bytes"] > 0

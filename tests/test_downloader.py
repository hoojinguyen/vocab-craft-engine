"""Tests for parallel downloader."""

import pytest
from pathlib import Path
from unittest.mock import patch
from src.ingestion.downloader import DownloadTask, download_all_parallel


def test_download_task_creates():
    task = DownloadTask(url="https://example.com/file.zip", dest=Path("/tmp/file.zip"))
    assert task.url == "https://example.com/file.zip"
    assert task.dest == Path("/tmp/file.zip")


@patch("src.ingestion.downloader._download_one")
def test_download_all_parallel_runs(mock_download, tmp_path):
    mock_download.return_value = True
    tasks = [
        DownloadTask(url="https://ex.com/a.zip", dest=Path(tmp_path / "a.zip")),
        DownloadTask(url="https://ex.com/b.zip", dest=Path(tmp_path / "b.zip")),
    ]
    results = download_all_parallel(tasks, max_workers=2)
    assert mock_download.call_count == 2
    assert all(results.values())


def test_download_skips_existing_files(tmp_path):
    existing = tmp_path / "exists.zip"
    existing.write_bytes(b"content")
    tasks = [DownloadTask(url="https://ex.com/exists.zip", dest=existing)]
    with patch("src.ingestion.downloader._download_one") as mock:
        results = download_all_parallel(tasks, max_workers=1)
        assert mock.call_count == 0

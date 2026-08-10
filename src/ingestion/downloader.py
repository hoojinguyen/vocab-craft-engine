"""Parallel downloader with resume support."""

import logging
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    url: str
    dest: Path
    min_size: int = 1
    description: str = ""


def download_all_parallel(tasks: List[DownloadTask], max_workers: int = 4) -> Dict[str, bool]:
    """Download multiple files in parallel. Returns {url: success}."""
    results: Dict[str, bool] = {}
    pending = [t for t in tasks if not _already_has(t.dest, t.min_size)]

    if not pending:
        logger.info("All %d files already exist — skipping downloads.", len(tasks))
        return {t.url: True for t in tasks}

    logger.info("Downloading %d/%d files (%d workers)...", len(pending), len(tasks), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_download_one, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results[task.url] = future.result()
            except Exception as e:
                logger.error("Download failed for %s: %s", task.url, e)
                results[task.url] = False

    for t in tasks:
        if t.url not in results:
            results[t.url] = True

    succeeded = sum(1 for v in results.values() if v)
    logger.info("Downloads complete: %d/%d succeeded.", succeeded, len(tasks))
    return results


def _already_has(path: Path, min_size: int) -> bool:
    return path.exists() and path.stat().st_size >= min_size


def _download_one(task: DownloadTask) -> bool:
    """Download a single file with resume support."""
    task.dest.parent.mkdir(parents=True, exist_ok=True)
    existing = task.dest.stat().st_size if task.dest.exists() else 0

    if existing >= task.min_size:
        logger.info("  [skip] %s already exists.", task.dest.name)
        return True

    logger.info("  [download] %s -> %s", task.url, task.dest)

    try:
        request = urllib.request.Request(task.url)
        if existing > 0:
            request.add_header("Range", f"bytes={existing}-")

        with urllib.request.urlopen(request, timeout=60) as resp:
            if resp.status == 200 and existing > 0:
                existing = 0
                mode = "wb"
            else:
                mode = "ab"

            with open(task.dest, mode) as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)

        size_mb = task.dest.stat().st_size / 1e6
        logger.info("  [done] %s (%.1f MB)", task.dest.name, size_mb)
        return True

    except Exception as e:
        logger.error("  [fail] %s: %s", task.dest.name, e)
        return False

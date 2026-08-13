"""Pipeline V2 Benchmark Utility."""

import logging
import time
from typing import Any, Dict

try:
    import psutil
except ImportError:
    psutil = None

from config.settings import STAGING_DUCKDB_PATH
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.cli import parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry

logger = logging.getLogger(__name__)


def run_benchmark(dry_run: bool = False) -> Dict[str, Any]:
    if psutil:
        process = psutil.Process()
        start_mem = process.memory_info().rss
    else:
        start_mem = 0
    start_time = time.monotonic()

    db_mgr = DuckDBManager(db_path=STAGING_DUCKDB_PATH)
    db_mgr.init_schema()

    args_list = ["--dry-run"] if dry_run else []
    args = parse_arguments(args_list)

    context = PipelineContext(db_manager=db_mgr, args=args)
    registry = get_default_registry()
    orchestrator = PipelineOrchestrator(registry=registry)

    summary = orchestrator.run(context)

    end_time = time.monotonic()
    peak_mem = process.memory_info().rss if psutil else 0

    elapsed = round(end_time - start_time, 2)
    mem_mb = round((peak_mem - start_mem) / (1024 * 1024), 2)

    db_mgr.close()

    return {
        "total_time_seconds": elapsed,
        "memory_peak_mb": mem_mb,
        "results_count": len(summary.results),
        "has_failures": summary.has_failures,
    }


if __name__ == "__main__":
    report = run_benchmark(dry_run=True)
    print(f"Benchmark Report: {report}")

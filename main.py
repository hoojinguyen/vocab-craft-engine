"""
Main Execution Pipeline for English Dataset System Engine.
Orchestrates DAG-based Parallel Execution with DuckDB Staging.
"""

import logging
import sys

from config.settings import STAGING_DUCKDB_PATH
from scripts.download_raw_data import download_all_raw_data
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.cli import REQUIRED_RAW_FILES, get_missing_raw_files, parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    args = parse_arguments()
    missing_raw = get_missing_raw_files(REQUIRED_RAW_FILES)
    if missing_raw:
        logger.info("Raw data files missing: %s", [str(p) for p in missing_raw])
        logger.info("Raw data files check/download in progress...")
        download_all_raw_data()

    db_manager = DuckDBManager(db_path=STAGING_DUCKDB_PATH)
    db_manager.init_schema()

    try:
        context = PipelineContext(db_manager=db_manager, args=args)
        registry = get_default_registry()
        orchestrator = PipelineOrchestrator(registry=registry)

        summary = orchestrator.run(context)
        if summary.has_failures:
            logger.error("Pipeline failed with error(s).")
            sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()

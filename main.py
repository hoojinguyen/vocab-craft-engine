"""
Main Execution Pipeline for English Dataset System Engine.
Orchestrates Ingestion, NLP Enrichment, Collocation Extraction, Dialogue Trees, Reflex Drill Generation, and SQLite Export.
Now modularized via src.pipeline steps & orchestrator.
"""

import sys
import logging
from src.pipeline.cli import parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry
from src.db.staging_db import DatabaseManager
from config.settings import EXPORT_SQLITE_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def main():
    args = parse_arguments()
    db_manager = DatabaseManager(db_path=EXPORT_SQLITE_PATH)
    context = PipelineContext(db_manager=db_manager, args=args)

    registry = get_default_registry()
    orchestrator = PipelineOrchestrator(registry=registry)

    summary = orchestrator.run(context)
    if summary.has_failures:
        logger.error("Pipeline failed with error(s).")
        sys.exit(1)

if __name__ == "__main__":
    main()

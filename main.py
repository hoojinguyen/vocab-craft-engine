"""Main Execution Pipeline for English Dataset System Engine.

Orchestrates DAG-based Parallel Execution with DuckDB Staging.
"""

import logging
import sys

import config.settings
from scripts.download_raw_data import download_all_raw_data
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.cli import REQUIRED_RAW_FILES, get_missing_raw_files, parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.state_manager import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def handle_status(db_manager: DuckDBManager):
    conn = db_manager.get_connection()
    rows = conn.execute(
        "SELECT step_name, status, row_count, duration_secs, completed_at FROM _pipeline_meta ORDER BY started_at"
    ).fetchall()
    print("\n=== PIPELINE STEP STATUS ===")
    print(
        f"{'STEP NAME':<25} {'STATUS':<12} {'ITEMS':<10} {'TIME (s)':<10} {'COMPLETED AT'}"
    )
    print("-" * 75)
    for r in rows:
        dur = r[3] if r[3] is not None else 0.0
        print(f"{r[0]:<25} {r[1]:<12} {r[2]:<10} {dur:<10.2f} {r[4]}")
    print()


def handle_reset(
    db_manager: DuckDBManager, step_name: str | None = None, reset_all: bool = False
):
    from src.pipeline.core.orchestrator import PipelineOrchestrator
    from src.pipeline.core.registry import get_default_registry

    state_mgr = StateManager(db_manager)
    registry = get_default_registry()
    dag = PipelineOrchestrator(registry=registry).dag

    if reset_all:
        conn = db_manager.get_connection()
        conn.execute("DELETE FROM _pipeline_meta")
        logger.info("Reset all step execution metadata.")
    elif step_name and dag:
        state_mgr.invalidate_step(step_name, dag)
        logger.info("Invalidated step '%s' and downstream dependencies.", step_name)


def handle_export(db_manager: DuckDBManager, export_format: str):
    from src.pipeline.core.registry import get_default_registry

    format_map = {
        "sqlite": "export_sqlite",
        "json": "export_json",
        "core3000": "export_core3000",
    }
    step_name = format_map.get(export_format, "export_sqlite")
    registry = get_default_registry()
    step = registry.get_step(step_name)
    if step:
        context = PipelineContext(db_manager=db_manager)
        step.run(context)
        logger.info("Executed export format '%s' (%s).", export_format, step_name)


def main():
    args = parse_arguments()

    if getattr(args, "command", None) == "curriculum":
        from src.learning.cli import run_parsed_curriculum_command

        raise SystemExit(run_parsed_curriculum_command(args))

    db_manager = DuckDBManager(db_path=config.settings.STAGING_DUCKDB_PATH)
    db_manager.init_schema()

    try:
        if getattr(args, "command", None) == "status":
            handle_status(db_manager)
            return

        if getattr(args, "command", None) == "reset":
            handle_reset(
                db_manager,
                step_name=getattr(args, "step", None),
                reset_all=getattr(args, "all", False),
            )
            return

        if getattr(args, "command", None) == "export":
            handle_export(db_manager, export_format=getattr(args, "format", "sqlite"))
            return

        missing_raw = get_missing_raw_files(REQUIRED_RAW_FILES)
        if missing_raw:
            logger.info("Raw data files missing: %s", [str(p) for p in missing_raw])
            logger.info("Raw data files check/download in progress...")
            download_all_raw_data()

        context = PipelineContext(db_manager=db_manager, args=args)
        from src.pipeline.core.orchestrator import PipelineOrchestrator
        from src.pipeline.core.registry import get_default_registry

        registry = get_default_registry()
        workers = getattr(args, "workers", 4)
        orchestrator = PipelineOrchestrator(registry=registry, max_workers=workers)

        summary = orchestrator.run(context)
        handle_status(db_manager)
        if summary.has_failures:
            logger.error("Pipeline completed with errors.")
            sys.exit(1)
        else:
            logger.info(
                "Pipeline completed successfully in %.2f seconds.",
                summary.total_time_seconds,
            )
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()

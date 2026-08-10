"""DAG-based pipeline entry point for English Dataset System Engine v2.0."""

import sys
import logging
import time
import argparse

from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor
from src.pipeline.registry import CheckpointRegistry
from src.db.duckdb_manager import DuckDBManager
from src.db.sqlite_manager import SQLiteBulkWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="English Dataset Pipeline v2.0")
    parser.add_argument("--force-reset", action="store_true", help="Force re-run all stages.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Kaikki ingestion.")
    parser.add_argument("--vi-budget", type=int, default=1000, help="Max VI translations per run.")
    parser.add_argument("--audio-limit", type=int, default=5000, help="Max audio files to generate.")
    parser.add_argument("--build-core-pack", action="store_true", help="Build Core 3000 word pack.")
    parser.add_argument("--stage", type=str, default=None, help="Run single stage: ingest|transform|enrich|export|pack.")
    return parser.parse_args()


def build_dag(ctx: PipelineContext, registry: CheckpointRegistry) -> DAGExecutor:
    from src.stages.stage_1_ingest import stage_1_ingest
    from src.stages.stage_2_transform import stage_2_transform
    from src.stages.stage_3_enrich import stage_3_enrich
    from src.stages.stage_4_export import stage_4_export

    dag = DAGExecutor(registry=registry)
    dag.add_step("ingest", stage_1_ingest)
    dag.add_step("transform", stage_2_transform, depends={"ingest"})
    dag.add_step("enrich", stage_3_enrich, depends={"transform"})
    dag.add_step("export", stage_4_export, depends={"enrich"})

    if ctx.build_core_pack:
        from src.stages.stage_5_core_pack import stage_5_core_pack
        dag.add_step("pack", stage_5_core_pack, depends={"export"})

    return dag


def run_pipeline():
    args = parse_args()
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("   VOCABCRAFT ENGINE v2.0 - DAG PIPELINE")
    logger.info("=" * 60)

    ctx = PipelineContext(
        force_reset=args.force_reset,
        vi_budget=args.vi_budget,
        audio_limit=args.audio_limit,
        build_core_pack=args.build_core_pack,
    )

    registry = CheckpointRegistry(ctx.checkpoint_dir)

    ctx.duckdb_conn = DuckDBManager(ctx.duckdb_path)
    ctx.duckdb_conn.connect()

    dag = build_dag(ctx, registry)

    if args.stage:
        logger.info("Running single stage: %s", args.stage)
        single_dag = DAGExecutor(registry=registry)
        stage_funcs = {
            "ingest": __import__("src.stages.stage_1_ingest", fromlist=["stage_1_ingest"]).stage_1_ingest,
            "transform": __import__("src.stages.stage_2_transform", fromlist=["stage_2_transform"]).stage_2_transform,
            "enrich": __import__("src.stages.stage_3_enrich", fromlist=["stage_3_enrich"]).stage_3_enrich,
            "export": __import__("src.stages.stage_4_export", fromlist=["stage_4_export"]).stage_4_export,
        }
        if args.stage in stage_funcs:
            single_dag.add_step(args.stage, stage_funcs[args.stage])
            single_dag.execute(ctx, force_reset=args.force_reset)
        else:
            logger.error("Unknown stage: %s", args.stage)
            sys.exit(1)
    else:
        dag.execute(ctx, force_reset=args.force_reset)

    ctx.duckdb_conn.close()

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("   PIPELINE COMPLETE IN %.1f SECONDS (%.1f min)", elapsed, elapsed / 60)
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()

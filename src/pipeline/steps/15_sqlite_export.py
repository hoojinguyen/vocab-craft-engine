import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.export.sqlite_exporter import SQLiteExporter

logger = logging.getLogger(__name__)


class SQLiteExportStep(BaseStep):
    name = "sqlite_export"
    description = "Build composite indexes, enable WAL mode, and export optimized SQLite DB"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("Packaging & Optimizing SQLite Mobile Database...")
        exporter = SQLiteExporter(context.db_manager.db_path)
        export_info = exporter.optimize_and_package()
        avg_speed = exporter.benchmark_reflex_query_speed(iterations=20)
        logger.info("   -> Reflex Query Benchmark Speed: %.2f ms", avg_speed)

        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=1,
            metrics={"size_mb": export_info["size_mb"], "reflex_speed_ms": avg_speed},
        )

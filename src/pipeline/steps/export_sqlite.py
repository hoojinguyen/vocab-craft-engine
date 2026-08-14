"""SQLite Export Step V2."""

import logging
from typing import Tuple
from config.settings import EXPORT_SQLITE_PATH, OUTPUT_DIR
from src.export.packager import DatasetPackager
from src.export.sqlite_exporter import SqliteExporter
from src.export.verifier import DatasetVerifier
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus

logger = logging.getLogger(__name__)


class ExportSQLiteStep(BaseStep):
    name = "export_sqlite"
    description = "Export DuckDB staging database to SQLite english_dataset.db"
    depends_on = ["enrich_translation", "transform_relations", "enrich_reflex", "enrich_scenarios"]
    produces = ["english_dataset.db"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = SqliteExporter()
        counts = exporter.export(ctx.db, EXPORT_SQLITE_PATH)

        # Verify integrity of exported SQLite database
        verifier = DatasetVerifier()
        report = verifier.verify(EXPORT_SQLITE_PATH)
        if not report.is_valid:
            logger.error("Exported SQLite verification failed: %s", report.errors)
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                items_processed=sum(counts.values()),
                error="; ".join(report.errors),
            )

        # Create distribution package (.zip, .sha256, manifest.json)
        packager = DatasetPackager()
        packager.package(
            db_path=EXPORT_SQLITE_PATH,
            output_dir=OUTPUT_DIR,
            version="2.0.0",
            table_counts=counts,
        )

        total_rows = sum(counts.values())
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=total_rows,
            data_metrics=counts,
        )

"""SQLite Export Step V2."""

from typing import Tuple
from config.settings import EXPORT_SQLITE_PATH
from src.export.sqlite_exporter import SQLiteExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportSQLiteStep(BaseStep):
    name = "export_sqlite"
    description = "Export DuckDB staging database to SQLite english_dataset.db"
    depends_on = ["enrich_translation", "transform_relations", "enrich_reflex", "enrich_scenarios"]
    produces = ["english_dataset.db"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = SQLiteExporter()
        count = exporter.export(ctx.db, EXPORT_SQLITE_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

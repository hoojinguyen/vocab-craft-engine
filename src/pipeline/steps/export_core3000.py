"""Core 3000 Export Step V2."""

from typing import Tuple
from config import settings
from src.export.core_exporter import CoreExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportCore3000Step(BaseStep):
    name = "export_core3000"
    description = "Build and export curated core_3000.db iOS bundle with quality audit"
    depends_on = ["export_sqlite"]
    produces = ["core_3000.db", "quality_report.md"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = CoreExporter()
        report_path = settings.OUTPUT_DIR / "quality_report.md"
        count = exporter.export_core_bundle(
            db_mgr=ctx.db,
            target_path=settings.OUTPUT_DIR / "core_3000.db",
            report_path=report_path,
            core_limit=3000,
            ngsl_path=settings.NGSL_PATH,
            oxford_path=settings.OXFORD_3000_PATH,
        )
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=count,
            message=f"Exported {count} core words to core_3000.db with quality report at {report_path}",
        )

"""Core 3000 Export Step V2."""

from typing import Tuple
from config.settings import OUTPUT_DIR
from src.export.core_exporter import CoreExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportCore3000Step(BaseStep):
    name = "export_core3000"
    description = "Build and export curated core_3000.db iOS bundle"
    depends_on = ["export_sqlite"]
    produces = ["core_3000.db"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = CoreExporter()
        count = exporter.export_core_bundle(ctx.db, OUTPUT_DIR / "core_3000.db")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

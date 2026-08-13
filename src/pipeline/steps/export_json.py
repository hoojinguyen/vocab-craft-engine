"""JSON Dataset Export Step V2."""

from typing import Tuple
from config.settings import OUTPUT_DIR
from src.export.json_exporter import JsonExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportJsonStep(BaseStep):
    name = "export_json"
    description = "Export dataset.json using orjson"
    depends_on = ["enrich_translation", "transform_relations"]
    produces = ["dataset.json"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = JsonExporter()
        count = exporter.export(ctx.db, OUTPUT_DIR / "dataset.json")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

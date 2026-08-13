"""Reflex Drill Enrichment Step V2."""

from typing import Tuple
from src.enrichment.reflex_builder import ReflexBuilder
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichReflexStep(BaseStep):
    name = "enrich_reflex"
    description = "Generate reflex drill exercises"
    depends_on = ["transform_linking"]
    produces = ["reflex_drills"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("reflex_drills")
        if count > 0:
            return True, f"Reflex drills present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        builder = ReflexBuilder()
        count = builder.build(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

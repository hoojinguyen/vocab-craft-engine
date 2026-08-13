"""Dialogue Scenario Enrichment Step V2."""

from typing import Tuple
from src.enrichment.scenario_builder import ScenarioBuilder
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichScenariosStep(BaseStep):
    name = "enrich_scenarios"
    description = "Generate dialogue tree scenarios"
    depends_on = ["transform_linking"]
    produces = ["dialogue_trees", "dialogue_nodes"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("dialogue_trees")
        if count > 0:
            return True, f"Dialogue trees present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        builder = ScenarioBuilder()
        count = builder.build(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

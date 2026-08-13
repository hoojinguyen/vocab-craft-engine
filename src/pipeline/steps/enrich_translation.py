"""Vietnamese Translation Enrichment Step V2."""

from typing import Tuple
from src.enrichment.translation import HybridTranslator
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichTranslationStep(BaseStep):
    name = "enrich_translation"
    description = "Translate definitions and phrases to Vietnamese"
    depends_on = ["ingest_kaikki", "transform_phrases"]
    produces = ["definitions", "phrases"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        translator = HybridTranslator(ctx.db)
        count = translator.translate_definitions()
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

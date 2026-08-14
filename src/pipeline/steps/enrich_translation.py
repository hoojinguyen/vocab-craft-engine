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
        vi_budget = getattr(ctx.args, "vi_budget", None) if getattr(ctx, "args", None) else None
        translator = HybridTranslator(ctx.db)
        count_defs = translator.translate_definitions(limit=vi_budget)
        count_phrases = translator.translate_phrases(limit=vi_budget)
        total = count_defs + count_phrases
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=total)


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

        try:
            conn = ctx.db.get_connection()
            def_count = conn.execute("SELECT count(*) FROM definitions WHERE definition_vi IS NULL AND definition_en IS NOT NULL").fetchone()[0]
            phrase_count = conn.execute("SELECT count(*) FROM phrases WHERE definition_vi IS NULL").fetchone()[0]
            expected_total = (min(def_count, vi_budget) if vi_budget else def_count) + (min(phrase_count, vi_budget) if vi_budget else phrase_count)
        except Exception:
            expected_total = 100

        progress = ctx.create_progress(self.name, total=max(1, expected_total)) if hasattr(ctx, "create_progress") else None
        translator = HybridTranslator(ctx.db)
        count_defs = translator.translate_definitions(limit=vi_budget, progress=progress)
        count_phrases = translator.translate_phrases(limit=vi_budget, progress=progress)
        total = count_defs + count_phrases
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=total)


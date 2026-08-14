"""Phrase and MWE Extraction Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.phrase_extractor import PhraseExtractor


class TransformPhrasesStep(BaseStep):
    name = "transform_phrases"
    description = "Extract phrases and multi-word expressions"
    depends_on = ["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]
    produces = ["phrases", "phrase_sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("phrases")
        if count > 0:
            return True, f"Phrases present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        extractor = PhraseExtractor()
        result = extractor.extract(ctx.db)
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=result.phrases_created,
        )

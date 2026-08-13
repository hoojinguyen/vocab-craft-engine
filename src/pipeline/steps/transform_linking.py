"""Sentence Linking Transform Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.sentence_linker import SentenceLinker


class TransformLinkingStep(BaseStep):
    name = "transform_linking"
    description = "Link words to matching sentences"
    depends_on = ["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]
    produces = ["word_sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("word_sentences")
        if count > 0:
            return True, f"Word sentences present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        linker = SentenceLinker()
        count = linker.link(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

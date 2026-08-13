"""Schema Init Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class SchemaInitStep(BaseStep):
    name = "schema_init"
    description = "Initialize DuckDB staging and internal database schema"
    depends_on = []
    produces = ["words", "definitions", "sentences", "word_sentences", "phrases", "phrase_sentences", "word_relations", "word_topics", "reflex_drills", "dialogue_trees", "dialogue_nodes"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ctx.db.init_schema()
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=15)

"""WordNet Ingestion Step V2."""

from typing import Tuple
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestWordNetStep(BaseStep):
    name = "ingest_wordnet"
    description = "Ingest WordNet vocabulary and lexical relations"
    depends_on = ["schema_init"]
    produces = ["words", "word_relations"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = WordNetIngestor()
        count = ingestor.ingest(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

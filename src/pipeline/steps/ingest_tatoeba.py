"""Tatoeba Sentence Ingestion Step V2."""

from typing import Tuple
from config.settings import TATOEBA_LINKS_PATH, TATOEBA_SENTENCES_PATH
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestTatoebaStep(BaseStep):
    name = "ingest_tatoeba"
    description = "Ingest Tatoeba EN-VI sentences"
    depends_on = ["schema_init"]
    produces = ["sentences"]
    execution_type = "cpu"
    source_files = [TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("sentences")
        if count > 0:
            return True, f"Sentences present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = TatoebaIngestor()
        count = ingestor.ingest_files(ctx.db, TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

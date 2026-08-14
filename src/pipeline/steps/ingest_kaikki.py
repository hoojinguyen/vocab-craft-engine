"""Kaikki Wiktionary Ingestion Step V2."""

from typing import Tuple
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.frequency_ingestor import FrequencyIngestor
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestKaikkiStep(BaseStep):
    name = "ingest_kaikki"
    description = "Ingest Kaikki Wiktionary JSON dump"
    depends_on = ["schema_init"]
    produces = ["words", "definitions"]
    execution_type = "cpu"
    source_files = [KAIKKI_JSON_PATH]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("words")
        if count > 0:
            return True, f"Already ingested ({count} words)"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = KaikkiIngestor()
        count = ingestor.ingest(ctx.db, KAIKKI_JSON_PATH)
        if SUBTLEX_FREQ_PATH.exists():
            freq_ingestor = FrequencyIngestor()
            freq_ingestor.populate_frequency_ranks(ctx.db, SUBTLEX_FREQ_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)


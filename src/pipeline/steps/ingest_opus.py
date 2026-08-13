"""OPUS Parallel Sentence Ingestion Step V2."""

from typing import Tuple
from config.settings import OPENSUBTITLES_EN, OPENSUBTITLES_VI
from src.ingestion.opus_ingestor import OpusIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestOpusStep(BaseStep):
    name = "ingest_opus"
    description = "Ingest OPUS OpenSubtitles parallel sentences"
    depends_on = ["schema_init"]
    produces = ["sentences"]
    execution_type = "cpu"
    source_files = [OPENSUBTITLES_EN, OPENSUBTITLES_VI]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = OpusIngestor()
        count = ingestor.ingest_pair(ctx.db, OPENSUBTITLES_EN, OPENSUBTITLES_VI, source="opus")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

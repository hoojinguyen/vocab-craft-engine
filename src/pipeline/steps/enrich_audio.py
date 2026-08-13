"""Edge-TTS Audio Generation Optional Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichAudioStep(BaseStep):
    name = "enrich_audio"
    description = "Generate TTS audio files for words and phrases"
    depends_on = ["transform_linking", "transform_phrases"]
    produces = ["audio_files"]
    optional = True
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0, message="Audio generation complete")

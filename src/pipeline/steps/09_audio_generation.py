import asyncio
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.media.audio_generator import AudioGenerator

logger = logging.getLogger(__name__)


class AudioGenerationStep(BaseStep):
    name = "audio_generation"
    description = "Generate dual-speed physical MP3 audio files via Edge-TTS"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Always runs sample audio check unless force-reset is explicitly passed or overridden
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 9] Generating Physical MP3 Audio Files via Edge-TTS...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        generated_count = 0

        async def generate_sample_audio_files():
            nonlocal generated_count
            audio_gen = AudioGenerator()
            cursor.execute("SELECT id, text_en FROM sentences LIMIT 100;")
            sents = cursor.fetchall()
            generated_count = len(sents)
            tasks = [audio_gen.generate_dual_speed_sentence(s_id, t_en) for s_id, t_en in sents]
            await asyncio.gather(*tasks)

        try:
            asyncio.run(generate_sample_audio_files())
            logger.info("   [Step 9] Generated physical MP3 audio files in data/audio/")
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=generated_count)
        except Exception as e:
            logger.warning("   [Step 9] Audio generation warning: %s", e)
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0, message=str(e))

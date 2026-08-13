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

        async def generate_sentence_audio_files():
            nonlocal generated_count
            audio_gen = AudioGenerator()
            cursor.execute("SELECT id, text_en, audio_path FROM sentences;")
            all_sents = cursor.fetchall()

            sents_needing_audio = []
            for s_id, t_en, audio_path in all_sents:
                if not audio_path:
                    sents_needing_audio.append((s_id, t_en))
                else:
                    file_path = audio_gen.output_dir / audio_path
                    if not file_path.exists() or file_path.stat().st_size == 0:
                        sents_needing_audio.append((s_id, t_en))

            if not sents_needing_audio:
                return

            tasks = [audio_gen.generate_dual_speed_sentence(s_id, t_en) for s_id, t_en in sents_needing_audio]
            results = await asyncio.gather(*tasks)

            for (s_id, t_en), res in zip(sents_needing_audio, results):
                std_path = res.get("standard_path") if isinstance(res, dict) else None
                fast_path = res.get("fast_path") if isinstance(res, dict) else None
                if not std_path or not fast_path:
                    logger.warning("   [Step 9] Audio generation missing standard or fast path for sentence %s", s_id)
                    raise RuntimeError(f"Audio generation missing standard or fast path for sentence {s_id}")

                rel_audio_path = f"sent_{s_id}_std.mp3"
                cursor.execute("UPDATE sentences SET audio_path = ? WHERE id = ?;", (rel_audio_path, s_id))
                generated_count += 1

            conn.commit()

        try:
            asyncio.run(generate_sentence_audio_files())
            logger.info("   [Step 9] Generated physical MP3 audio files in data/audio/")
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=generated_count)
        except Exception as e:
            logger.error("   [Step 9] Audio generation error: %s", e)
            raise e

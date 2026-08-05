"""
Parallel Text-to-Speech Audio Generator for English Dataset System Engine.
Uses edge-tts with asyncio Semaphore rate-limiting and exponential backoff retries.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import edge_tts

from config.settings import (
    AUDIO_DIR,
    MAX_CONCURRENT_AUDIO,
    AUDIO_RETRY_COUNT,
    TTS_VOICES,
    TTS_SPEED_STANDARD,
    TTS_SPEED_FAST_REFLEX
)

logger = logging.getLogger(__name__)


class AudioGenerator:
    """Generates MP3 audio files using edge-tts with rate limiting and exponential backoff retries."""

    def __init__(
        self,
        output_dir: Path = AUDIO_DIR,
        max_concurrent: int = MAX_CONCURRENT_AUDIO,
        retry_count: int = AUDIO_RETRY_COUNT
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.retry_count = retry_count

    async def generate_audio_file(
        self,
        text: str,
        output_filename: str,
        voice: str = TTS_VOICES["US_FEMALE"],
        speed: str = TTS_SPEED_STANDARD
    ) -> Optional[Path]:
        """
        Generates a single MP3 audio file with rate-limiting and retries.
        Returns the output file Path on success, None on failure.
        """
        output_path = self.output_dir / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        async with self.semaphore:
            for attempt in range(1, self.retry_count + 1):
                try:
                    communicate = edge_tts.Communicate(text, voice=voice, rate=speed)
                    await communicate.save(str(output_path))

                    if output_path.exists() and output_path.stat().st_size > 0:
                        logger.debug("Successfully generated audio: %s", output_filename)
                        return output_path
                except Exception as e:
                    logger.warning(
                        "Attempt %d/%d failed for audio '%s': %s",
                        attempt, self.retry_count, output_filename, e
                    )
                    if attempt < self.retry_count:
                        # Exponential backoff delay: 1s, 3s, 7s...
                        await asyncio.sleep(2 ** (attempt - 1))

        logger.error("Failed to generate audio for '%s' after %d retries.", text, self.retry_count)
        return None

    async def generate_dual_speed_sentence(
        self,
        sentence_id: int,
        text_en: str,
        voice: str = TTS_VOICES["US_FEMALE"]
    ) -> Dict[str, Optional[Path]]:
        """
        Generates standard (1.0x) and fast reflex (1.2x) audio files for a sentence.
        """
        fn_std = f"sent_{sentence_id}_std.mp3"
        fn_fast = f"sent_{sentence_id}_fast.mp3"

        std_path, fast_path = await asyncio.gather(
            self.generate_audio_file(text_en, fn_std, voice=voice, speed=TTS_SPEED_STANDARD),
            self.generate_audio_file(text_en, fn_fast, voice=voice, speed=TTS_SPEED_FAST_REFLEX)
        )

        return {
            "standard_path": std_path,
            "fast_path": fast_path
        }

    async def generate_dual_speed_phrase(
        self,
        phrase_id: int,
        text_en: str,
        voice: str = TTS_VOICES["US_FEMALE"]
    ) -> Dict[str, Optional[Path]]:
        """
        Generates standard (1.0x) and fast reflex (1.2x) audio files for a phrase.
        Uses phrase_{id}_*.mp3 naming to avoid collision with sentence audio.
        """
        fn_std = f"phrase_{phrase_id}_std.mp3"
        fn_fast = f"phrase_{phrase_id}_fast.mp3"

        std_path, fast_path = await asyncio.gather(
            self.generate_audio_file(text_en, fn_std, voice=voice, speed=TTS_SPEED_STANDARD),
            self.generate_audio_file(text_en, fn_fast, voice=voice, speed=TTS_SPEED_FAST_REFLEX)
        )

        return {
            "standard_path": std_path,
            "fast_path": fast_path
        }

    async def generate_dual_speed_word(
        self,
        word_id: int,
        text_en: str,
        voice: str = TTS_VOICES["US_FEMALE"]
    ) -> Dict[str, Optional[Path]]:
        """
        Generates standard (1.0x) and fast reflex (1.2x) audio for a single
        word. Files land in std/ and fast/ subdirectories (w_{id}_*.mp3),
        mirroring the pack's relative path layout.
        """
        fn_std = f"std/w_{word_id}_std.mp3"
        fn_fast = f"fast/w_{word_id}_fast.mp3"

        std_path, fast_path = await asyncio.gather(
            self.generate_audio_file(text_en, fn_std, voice=voice, speed=TTS_SPEED_STANDARD),
            self.generate_audio_file(text_en, fn_fast, voice=voice, speed=TTS_SPEED_FAST_REFLEX)
        )

        return {
            "standard_path": std_path,
            "fast_path": fast_path
        }

    async def generate_batch_sentences(
        self,
        sentences: List[Dict[str, Any]],
        voice: str = TTS_VOICES["US_FEMALE"]
    ) -> List[Dict[str, Any]]:
        """
        Batch generates audio for a list of sentences concurrently.
        """
        tasks = [
            self.generate_dual_speed_sentence(s["id"], s["text_en"], voice=voice)
            for s in sentences
        ]
        results = await asyncio.gather(*tasks)
        return results

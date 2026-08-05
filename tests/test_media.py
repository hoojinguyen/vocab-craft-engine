"""
Unit tests for Media Pipeline in src.media (IPAMapper & AudioGenerator)
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from src.media.ipa_mapper import IPAMapper
from src.media.audio_generator import AudioGenerator


def test_ipa_mapper():
    mapper = IPAMapper()

    # Preserves existing valid IPA
    existing = mapper.get_ipa("cat", existing_ipa="kæt")
    assert existing == "kæt"

    # G2P fallback for word without existing IPA
    fallback = mapper.get_ipa("cat")
    assert fallback is not None
    assert len(fallback) > 0


@pytest.mark.asyncio
async def test_audio_generator_single_file(tmp_path: Path):
    audio_gen = AudioGenerator(output_dir=tmp_path, max_concurrent=2, retry_count=1)

    # Mock edge_tts Communicate save method to avoid external network calls during unit tests
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        # Simulate creating dummy file on save
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        out_path = await audio_gen.generate_audio_file(
            text="Hello world!",
            output_filename="test_hello.mp3"
        )

        assert out_path is not None
        assert out_path.exists()
        assert out_path.read_bytes() == b"MOCK_MP3_DATA"


@pytest.mark.asyncio
async def test_audio_generator_dual_speed(tmp_path: Path):
    audio_gen = AudioGenerator(output_dir=tmp_path, max_concurrent=2, retry_count=1)

    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        res = await audio_gen.generate_dual_speed_sentence(
            sentence_id=42,
            text_en="How are you?"
        )

        assert res["standard_path"] is not None
        assert res["fast_path"] is not None
        assert res["standard_path"].name == "sent_42_std.mp3"
        assert res["fast_path"].name == "sent_42_fast.mp3"


@pytest.mark.asyncio
async def test_audio_generator_dual_speed_phrase(tmp_path: Path):
    audio_gen = AudioGenerator(output_dir=tmp_path, max_concurrent=2, retry_count=1)

    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        res = await audio_gen.generate_dual_speed_phrase(
            phrase_id=7,
            text_en="break a leg"
        )

        assert res["standard_path"] is not None
        assert res["fast_path"] is not None
        assert res["standard_path"].name == "phrase_7_std.mp3"
        assert res["fast_path"].name == "phrase_7_fast.mp3"


def test_audio_generator_semaphore_across_event_loops(tmp_path: Path):
    audio_gen = AudioGenerator(output_dir=tmp_path, max_concurrent=2, retry_count=1)

    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        async def b1():
            return await asyncio.gather(*[audio_gen.generate_audio_file(f"t1_{i}", f"w1_{i}.mp3") for i in range(5)])

        async def b2():
            return await asyncio.gather(*[audio_gen.generate_audio_file(f"t2_{i}", f"w2_{i}.mp3") for i in range(5)])

        res1 = asyncio.run(b1())
        res2 = asyncio.run(b2())

        assert len(res1) == 5
        assert len(res2) == 5


"""
End-to-end test for the Step 4G multi-word expression pipeline stage.
"""

import json
import argparse
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import importlib
main_module = importlib.import_module("src.pipeline.steps.10_phrase_mwe")
from src.db.staging_db import DatabaseManager


@pytest.fixture
def phrase_environment(tmp_path: Path, monkeypatch):
    # Redirect ALL AudioGenerator output to a per-test tmp dir so tests
    # never read or write the production data/audio directory.
    audio_dir = tmp_path / "audio"
    init_defaults = main_module.AudioGenerator.__init__.__defaults__
    monkeypatch.setattr(
        main_module.AudioGenerator.__init__,
        "__defaults__",
        (audio_dir,) + init_defaults[1:]
    )
    # Sample Kaikki dump with multi-word entries
    kaikki_file = tmp_path / "kaikki.jsonl"
    entries = [
        {"word": "break a leg", "pos": "idiom", "sounds": [],
         "translations": [{"code": "vi", "word": "chúc may mắn"}],
         "senses": [{"glosses": ["A phrase of encouragement."]}]},
        {"word": "give up", "pos": "phrasal verb", "sounds": [],
         "translations": [],
         "senses": [{"glosses": ["To stop trying."]}]},
        {"word": "cat", "pos": "noun", "sounds": [],
         "translations": [], "senses": [{"glosses": ["An animal."]}]}
    ]
    kaikki_file.write_text(
        "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
    )

    # Sample SUBTLEX frequency CSV
    freq_file = tmp_path / "SUBTLEX_US.csv"
    freq_file.write_text(
        "Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW\n"
        "break,50000,125.4,4.7,1000,3.0\n"
        "leg,30000,90.0,4.4,800,2.9\n"
        "give,40000,110.0,4.5,900,2.9\n"
        "cat,20000,50.0,4.0,500,2.7\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(main_module, "KAIKKI_JSON_PATH", kaikki_file)
    monkeypatch.setattr(main_module, "SUBTLEX_FREQ_PATH", freq_file)

    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    db_manager.insert_sentences_batch([
        {"text_en": "Break a leg at the show tonight!", "text_vi": None,
         "difficulty_score": 2.0, "cefr_level": "B1", "audio_path": None, "source": "Tatoeba"},
        {"text_en": "I decided to give up smoking.", "text_vi": None,
         "difficulty_score": 1.5, "cefr_level": "A2", "audio_path": None, "source": "Tatoeba"}
    ])

    # Stub Translator to avoid network calls
    class StubTranslator:
        def translate_text(self, text):
            return text

    monkeypatch.setattr(main_module, "Translator", StubTranslator)

    yield db_manager, db_path
    db_manager.close()


def test_run_phrase_step_populates_db(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Mock edge-tts to avoid network calls during audio generation
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        stats = main_module.run_phrase_step(db_manager, args)

    assert stats["phrases"] == 2

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phrase, phrase_type, cefr_level, definition_vi FROM phrases ORDER BY phrase;")
    rows = cursor.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "break a leg"
    assert rows[0][1] == "idiom"
    assert rows[0][3] == "chúc may mắn"
    assert rows[1][0] == "give up"
    assert rows[1][1] == "phrasal_verb"

    # Example sentence links
    cursor.execute("SELECT COUNT(*) FROM phrase_sentences;")
    assert cursor.fetchone()[0] >= 2

    # Audio status recorded with actual output paths linked to rows
    cursor.execute("SELECT audio_std, audio_fast, audio_status FROM phrases;")
    rows = cursor.fetchall()
    assert len(rows) == 2
    for audio_std, audio_fast, audio_status in rows:
        assert audio_std is not None and audio_std.endswith("_std.mp3")
        assert audio_fast is not None and audio_fast.endswith("_fast.mp3")
        assert audio_status == "ok"


def test_run_phrase_step_checkpoint_skips(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Pre-populate enough phrases with complete audio to trigger the checkpoint
    audio_dir = db_path.parent / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    phrases = []
    for i in range(600):
        std_p = audio_dir / f"phrase_{i}_std.mp3"
        fast_p = audio_dir / f"phrase_{i}_fast.mp3"
        std_p.write_bytes(b"dummy")
        fast_p.write_bytes(b"dummy")
        phrases.append({
            "phrase": f"checkpoint phrase {i}", "phrase_type": "idiom", "pos": "idiom",
            "cefr_level": "B1", "difficulty_score": 2.0, "definition_en": "x",
            "definition_vi": None, "ipa": None,
            "audio_std": str(std_p), "audio_fast": str(fast_p),
            "audio_status": "ok"
        })
    db_manager.insert_phrases_batch(phrases)

    with patch.object(main_module, "PhraseParser") as mock_parser, \
         patch.object(main_module, "AudioGenerator") as mock_audio_gen:
        stats = main_module.run_phrase_step(db_manager, args)
        mock_parser.assert_not_called()
        mock_audio_gen.assert_not_called()

    assert stats["phrases"] == 600


def test_run_phrase_step_repairs_missing_audio(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Corrupted state left by a mid-loop crash: phrases exist but audio is
    # incomplete. The checkpoint must NOT skip — the step must re-run to repair.
    phrases = [
        {"phrase": f"checkpoint phrase {i}", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.0, "definition_en": "x",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
        for i in range(600)
    ]
    db_manager.insert_phrases_batch(phrases)

    # Mock edge-tts to write nothing: audio generation runs to completion but
    # every phrase is marked failed — the point is the step RAN and did not skip.
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save, \
         patch.object(main_module, "PhraseParser") as mock_parser:
        mock_save.side_effect = lambda target_path: None

        stats = main_module.run_phrase_step(db_manager, args)

        # Kaikki dump re-parsing is skipped since > 500 phrases exist
        mock_parser.assert_not_called()

    assert stats["phrases"] == 600

    # The repair pass rewrote every corrupted row: all 600 pre-seeded phrases
    # with missing audio got their status updated instead of being skipped
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM phrases WHERE audio_status = 'failed';")
    assert cursor.fetchone()[0] == 600


def test_run_phrase_step_audio_failure_sets_failed_status(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Mock edge-tts to produce no output files (silent failure) so paths stay None
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        mock_save.side_effect = lambda target_path: None

        stats = main_module.run_phrase_step(db_manager, args)

    assert stats["phrases"] == 2

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT audio_std, audio_fast, audio_status FROM phrases;")
    rows = cursor.fetchall()
    assert len(rows) == 2
    for audio_std, audio_fast, audio_status in rows:
        assert audio_std is None
        assert audio_fast is None
        assert audio_status == "failed"

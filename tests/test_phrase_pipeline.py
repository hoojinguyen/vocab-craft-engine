"""
End-to-end test for the Step 4G multi-word expression pipeline stage.
"""

import json
import argparse
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def phrase_environment(tmp_path: Path, monkeypatch):
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

    # Audio status recorded
    cursor.execute("SELECT audio_status FROM phrases;")
    statuses = {row[0] for row in cursor.fetchall()}
    assert statuses == {"ok"}


def test_run_phrase_step_checkpoint_skips(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Pre-populate enough phrases to trigger the checkpoint
    phrases = [
        {"phrase": f"checkpoint phrase {i}", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.0, "definition_en": "x",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
        for i in range(600)
    ]
    db_manager.insert_phrases_batch(phrases)

    with patch.object(main_module, "PhraseParser") as mock_parser:
        stats = main_module.run_phrase_step(db_manager, args)
        mock_parser.assert_not_called()

    assert stats["phrases"] == 600

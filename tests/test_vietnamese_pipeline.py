"""
End-to-end tests for the Step 4I Vietnamese translation backfill stage.
"""

import argparse
from pathlib import Path

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def vi_environment(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # words: dog graded (priority), cat ungraded
    cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('dog', 'noun', 'A1');")
    cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('cat', 'noun', NULL);")
    dog_id = cursor.execute("SELECT id FROM words WHERE lemma='dog'").fetchone()[0]
    cat_id = cursor.execute("SELECT id FROM words WHERE lemma='cat'").fetchone()[0]

    # definitions: dog polluted (vi == en), cat missing
    cursor.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi) VALUES (?, ?, ?);",
        (dog_id, "A loyal animal.", "A loyal animal.")
    )
    cursor.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi) VALUES (?, ?, ?);",
        (cat_id, "A small pet.", None)
    )

    # collocation polluted + phrase polluted
    cursor.execute(
        "INSERT INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level) VALUES (?, ?, 'verb_noun', 'B1');",
        ("take a break", "take a break")
    )
    cursor.execute(
        "INSERT INTO phrases (phrase, phrase_type, definition_en, definition_vi, audio_status) "
        "VALUES ('give up', 'phrasal_verb', 'To stop trying.', 'To stop trying.', 'ok');",
    )
    conn.commit()

    monkeypatch.setattr(main_module, "Translator", StubTranslator)
    yield db_manager
    db_manager.close()


class StubTranslator:
    """Fake Translator used by run_vietnamese_step; override translate_text per test."""

    @staticmethod
    def translate_text(text):
        return f"bản dịch của {text}"


def test_run_vietnamese_step_cleans_and_backfills(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    stats = main_module.run_vietnamese_step(db_manager, args)

    assert stats["definitions"] == 2
    assert stats["collocations"] == 1
    assert stats["phrases"] == 1

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions ORDER BY definition_en;")
    assert {row[0] for row in cursor.fetchall()} == {"bản dịch của A loyal animal.", "bản dịch của A small pet."}
    cursor.execute("SELECT meaning_vi FROM collocations;")
    assert cursor.fetchone()[0] == "bản dịch của take a break"
    cursor.execute("SELECT definition_vi FROM phrases;")
    assert cursor.fetchone()[0] == "bản dịch của To stop trying."


def test_run_vietnamese_step_checkpoint_skips(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    # Fill every candidate first so the checkpoint fires
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE definitions SET definition_vi = 'đã có bản dịch';")
    cursor.execute("UPDATE collocations SET meaning_vi = 'đã có bản dịch';")
    cursor.execute("UPDATE phrases SET definition_vi = 'đã có bản dịch';")
    conn.commit()

    with pytest.MonkeyPatch.context() as mp:
        calls = {"n": 0}
        class CountingTranslator:
            def __init__(self):
                calls["n"] += 1
        mp.setattr(main_module, "Translator", CountingTranslator)
        stats = main_module.run_vietnamese_step(db_manager, args)
        mp.undo()

    assert calls["n"] == 0
    assert stats == {"definitions": 0, "collocations": 0, "phrases": 0}


def test_run_vietnamese_step_mt_english_result_stays_null(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    class EnglishTranslator:
        @staticmethod
        def translate_text(text):
            return "The dog is an animal"

    monkeypatch.setattr(main_module, "Translator", EnglishTranslator)

    stats = main_module.run_vietnamese_step(db_manager, args)

    assert stats["definitions"] == 0
    assert stats["collocations"] == 0
    assert stats["phrases"] == 0

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM definitions WHERE definition_vi IS NOT NULL;")
    assert cursor.fetchone()[0] == 0


def test_run_vietnamese_step_idempotent(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    first = main_module.run_vietnamese_step(db_manager, args)
    second = main_module.run_vietnamese_step(db_manager, args)

    assert first["definitions"] == 2
    assert second["definitions"] == 0  # already translated -> checkpoint


def test_run_vietnamese_step_budget_caps_attempts(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False, vi_budget=1)

    calls = []

    class OneCallTranslator:
        @staticmethod
        def translate_text(text):
            calls.append(text)
            return f"bản dịch của {text}"

    vi_module = main_module
    from unittest.mock import patch
    with patch.object(vi_module, "Translator", OneCallTranslator):
        stats = main_module.run_vietnamese_step(db_manager, args)

    assert len(calls) == 1  # tiny budget -> only 1 MT attempt
    assert stats == {"definitions": 1, "collocations": 0, "phrases": 0}


def test_run_vi_budget_tiered_priority(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False, vi_budget=3)

    calls = []

    class SharedBudgetTranslator:
        @staticmethod
        def translate_text(text):
            calls.append(text)
            return f"bản dịch của {text}"

    main_module.Translator = SharedBudgetTranslator
    stats = main_module.run_vietnamese_step(db_manager, args)

    # budget 3: 2 definitions + 1 collocation attempted (priority order: definitions first)
    assert len(calls) == 3
    assert stats["definitions"] == 2
    assert stats["collocations"] == 1
    assert stats["phrases"] == 0


def test_run_vi_budget_zero_skips_all_mt(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False, vi_budget=0)

    calls = []

    class NoCallsTranslator:
        @staticmethod
        def translate_text(text):
            calls.append(text)
            return f"bản dịch của {text}"

    main_module.Translator = NoCallsTranslator
    stats = main_module.run_vietnamese_step(db_manager, args)

    assert calls == []
    assert stats == {"definitions": 0, "collocations": 0, "phrases": 0}


def test_run_vietnamese_step_prioritizes_graded_words(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False, vi_budget=1000)

    calls = []

    class BudgetTranslator:
        @staticmethod
        def translate_text(text):
            calls.append(text)
            # Only the FIRST call gets a valid translation — and it must be
            # the graded word's definition, proving graded-first ordering.
            if len(calls) == 1 and text == "A loyal animal.":
                return "Một loài vật trung thành."
            return ""

    monkeypatch.setattr(main_module, "Translator", BudgetTranslator)

    stats = main_module.run_vietnamese_step(db_manager, args)

    assert calls[0] == "A loyal animal."
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions d JOIN words w ON w.id = d.word_id WHERE w.lemma='dog';")
    assert cursor.fetchone()[0] == "Một loài vật trung thành."
    cursor.execute("SELECT definition_vi FROM definitions d JOIN words w ON w.id = d.word_id WHERE w.lemma='cat';")
    assert cursor.fetchone()[0] is None

import asyncio
import pytest
from unittest.mock import MagicMock, patch
import importlib

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus

mod_09 = importlib.import_module("src.pipeline.steps.09_audio_generation")
mod_10 = importlib.import_module("src.pipeline.steps.10_phrase_mwe")
mod_11 = importlib.import_module("src.pipeline.steps.11_relations_topics")
mod_12 = importlib.import_module("src.pipeline.steps.12_vietnamese_backfill")

AudioGenerationStep = mod_09.AudioGenerationStep
PhraseMWEStep = mod_10.PhraseMWEStep
RelationsTopicsStep = mod_11.RelationsTopicsStep
VietnameseBackfillStep = mod_12.VietnameseBackfillStep


# ---------------------------------------------------------------------------
# AudioGenerationStep (09)
# ---------------------------------------------------------------------------

def test_audio_generation_skip_condition():
    mock_db = MagicMock()
    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = AudioGenerationStep()

    skip, reason = step.should_skip(ctx)
    assert not skip
    assert reason == ""


def test_audio_generation_run_success():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "Hello world"), (2, "Good morning")]

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = AudioGenerationStep()

    with patch.object(mod_09, "AudioGenerator") as mock_gen_cls:
        mock_gen = mock_gen_cls.return_value
        
        async def dummy_gen(s_id, t_en):
            return {"standard_path": f"std_{s_id}.mp3", "fast_path": f"fast_{s_id}.mp3"}
        
        mock_gen.generate_dual_speed_sentence.side_effect = dummy_gen

        res = step.run(ctx)
        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 2


def test_audio_generation_run_exception_handled():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.side_effect = Exception("Audio service error")

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = AudioGenerationStep()

    res = step.run(ctx)
    assert res.status == StepStatus.SUCCESS
    assert res.items_processed == 0
    assert "Audio service error" in res.message


# ---------------------------------------------------------------------------
# PhraseMWEStep (10)
# ---------------------------------------------------------------------------

def test_phrase_mwe_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # existing_phrases = 600, missing_audio = 0
    mock_cursor.fetchone.side_effect = [(600,), (0,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = PhraseMWEStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason

    # Force reset overrides skip
    mock_args.force_reset = True
    skip, _ = step.should_skip(ctx)
    assert not skip


def test_phrase_mwe_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # fetchall for sentences and phrases
    mock_cursor.fetchall.side_effect = [
        [(1, "Kick the bucket", "A1")],  # sentence pool
        [(101, "kick the bucket")]       # stored phrases
    ]

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = PhraseMWEStep()

    mock_phrase_item = {
        "phrase": "kick the bucket",
        "phrase_type": "idiom",
        "pos": "verb",
        "definition_en": "to die",
        "definition_vi": "qua đời",
        "ipa": "/kɪk ðə ˈbʌkɪt/"
    }

    with patch.object(mod_10, "PhraseParser") as mock_parser_cls, \
         patch.object(mod_10, "PhraseGrader") as mock_grader_cls, \
         patch.object(mod_10, "Translator") as mock_translator_cls, \
         patch.object(mod_10, "PhraseExampleMatcher") as mock_matcher_cls, \
         patch.object(mod_10, "AudioGenerator") as mock_audio_cls:
        
        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_phrases.return_value = [mock_phrase_item]

        mock_grader = mock_grader_cls.return_value
        mock_grader.grade_phrase.return_value = {"cefr_level": "B2", "difficulty_score": 65.0}

        mock_matcher = mock_matcher_cls.return_value
        mock_matcher.match_phrases.return_value = [{"phrase_id": 101, "sentence_id": 1}]

        mock_audio = mock_audio_cls.return_value
        async def dummy_phrase_audio(p_id, text):
            return {"standard_path": "/tmp/std.mp3", "fast_path": "/tmp/fast.mp3"}
        mock_audio.generate_dual_speed_phrase.side_effect = dummy_phrase_audio

        res = step.run(ctx)
        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_db.insert_phrases_batch.assert_called_once()
        mock_db.insert_phrase_sentences_batch.assert_called_once()


# ---------------------------------------------------------------------------
# RelationsTopicsStep (11)
# ---------------------------------------------------------------------------

def test_relations_topics_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # relations = 60000, topics = 1500, inverse = 5000
    mock_cursor.fetchone.side_effect = [(60000,), (1500,), (5000,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = RelationsTopicsStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason

    mock_args.force_reset = True
    skip, _ = step.should_skip(ctx)
    assert not skip


def test_relations_topics_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # cursor.fetchall for lemma_map then natural_hypernyms
    mock_cursor.fetchall.side_effect = [
        [(1, "dog"), (2, "canine")],  # words
        [(1, "dog", 2, "kaikki")]     # natural hypernyms (dog -> hypernym -> canine)
    ]

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = RelationsTopicsStep()

    parsed_entry = {
        "word": "dog",
        "relations": [{"relation_type": "hypernym", "target": "canine", "source": "kaikki"}],
        "topics": [{"topic": "animals", "raw_topic": "Animals"}]
    }

    with patch.object(mod_11, "RelationParser") as mock_parser_cls:
        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_entries.return_value = [parsed_entry]

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 3  # 1 relation + 1 topic + 1 inverse relation
        mock_db.insert_word_relations_batch.assert_called()
        mock_db.insert_word_topics_batch.assert_called()


# ---------------------------------------------------------------------------
# VietnameseBackfillStep (12)
# ---------------------------------------------------------------------------

def test_vietnamese_backfill_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # def_missing = 0, col_missing = 0, phrase_missing = 0
    mock_cursor.fetchone.side_effect = [(0,), (0,), (0,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = VietnameseBackfillStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "No missing Vietnamese translations" in reason

    mock_args.force_reset = True
    skip, _ = step.should_skip(ctx)
    assert not skip


def test_vietnamese_backfill_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # priority definitions, priority collocations, priority phrases
    mock_cursor.fetchall.side_effect = [
        [(10, "a domesticated canine")],  # defs
        [(20, "barking dog")],            # colls
        [(30, "top dog")]                 # phrases
    ]

    mock_args = MagicMock()
    mock_args.vi_budget = 10
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = VietnameseBackfillStep()

    with patch.object(mod_12, "Translator") as mock_trans_cls, \
         patch.object(mod_12, "VietnameseTextValidator") as mock_val_cls, \
         patch.object(mod_12, "time"):
        
        mock_trans = mock_trans_cls.return_value
        mock_trans.translate_text.side_effect = lambda txt: f"Dịch: {txt}"

        mock_val = mock_val_cls.return_value
        mock_val.is_vietnamese.return_value = True

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 3
        assert mock_cursor.executemany.call_count >= 3

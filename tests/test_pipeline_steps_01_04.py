import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import importlib

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus

mod_01 = importlib.import_module("src.pipeline.steps.01_schema_init")
mod_02 = importlib.import_module("src.pipeline.steps.02_kaikki_ingestion")
mod_03 = importlib.import_module("src.pipeline.steps.03_tatoeba_ingestion")
mod_04 = importlib.import_module("src.pipeline.steps.04_sentence_linking")

SchemaInitStep = mod_01.SchemaInitStep
KaikkiIngestionStep = mod_02.KaikkiIngestionStep
TatoebaIngestionStep = mod_03.TatoebaIngestionStep
SentenceLinkingStep = mod_04.SentenceLinkingStep


def test_schema_init_step(tmp_path):
    mock_db = MagicMock()
    mock_args = MagicMock()
    mock_args.force_reset = False

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = SchemaInitStep()

    skip, _ = step.should_skip(ctx)
    assert not skip

    res = step.run(ctx)
    assert res.status == StepStatus.SUCCESS
    mock_db.init_schema.assert_called_once()


def test_schema_init_step_force_reset(tmp_path):
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_args = MagicMock()
    mock_args.force_reset = True

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = SchemaInitStep()

    with patch.object(mod_01, "SENTENCE_LINK_CHECKPOINT") as mock_ckpt, \
         patch.object(mod_01, "KAIKKI_INGEST_CHECKPOINT") as mock_kaikki_ckpt:
        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert mock_cursor.execute.call_count >= 11
        mock_ckpt.unlink.assert_called_once_with(missing_ok=True)
        mock_kaikki_ckpt.unlink.assert_called_once_with(missing_ok=True)
        mock_db.init_schema.assert_called_once()


def test_kaikki_ingestion_skip_condition():
    mock_db = MagicMock()
    mock_args = MagicMock()
    mock_args.force_reset = False
    mock_args.skip_dict = False

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = KaikkiIngestionStep()

    with patch.object(mod_02, "KAIKKI_INGEST_CHECKPOINT") as mock_ckpt:
        mock_ckpt.exists.return_value = True
        skip, reason = step.should_skip(ctx)
        assert skip
        assert "CHECKPOINT DETECTED" in reason


def test_kaikki_ingestion_skip_dict_flag():
    mock_db = MagicMock()
    mock_args = MagicMock()
    mock_args.skip_dict = True

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = KaikkiIngestionStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "--skip-dict flag active" in reason


def test_kaikki_ingestion_run(tmp_path):
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = KaikkiIngestionStep()

    mock_item = {
        "lemma": "hello",
        "pos": "noun",
        "ipa_uk": "həˈləʊ",
        "ipa_us": "həˈloʊ",
        "definitions": [
            {
                "definition_en": "A greeting",
                "definition_vi": "Lời chào",
                "example": "Hello world",
                "source": "kaikki"
            }
        ]
    }

    ckpt_file = tmp_path / ".kaikki_ingest_done"

    with patch.object(mod_02, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_02, "IPAMapper") as mock_ipa_cls, \
         patch.object(mod_02, "KaikkiParser") as mock_parser_cls, \
         patch.object(mod_02, "KAIKKI_INGEST_CHECKPOINT", ckpt_file):
        
        mock_grader = mock_grader_cls.return_value
        mock_grader.grade_word.return_value = ("A1", 100)

        mock_ipa = mock_ipa_cls.return_value
        mock_ipa.get_ipa.side_effect = lambda lemma, existing_ipa: existing_ipa

        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_stream.return_value = [mock_item]

        mock_db.get_word_id_by_lemma.return_value = 42

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 2
        mock_db.insert_words_batch.assert_called_once()
        mock_db.insert_definitions_batch.assert_called_once()
        assert ckpt_file.exists()


def test_tatoeba_ingestion_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.return_value = (2000,)

    mock_args = MagicMock()
    mock_args.force_reset = False

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = TatoebaIngestionStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason


def test_tatoeba_ingestion_run():
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = TatoebaIngestionStep()

    mock_pair = {
        "text_en": "Hello world.",
        "text_vi": "Xin chào thế giới.",
        "source": "Tatoeba"
    }

    with patch.object(mod_03, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_03, "TatoebaParser") as mock_parser_cls:
        
        mock_grader = mock_grader_cls.return_value
        mock_grader.grade_sentence.return_value = {"difficulty_score": 1.5, "cefr_level": "A1"}

        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_aligned_pairs.return_value = [mock_pair]

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_db.insert_sentences_batch.assert_called_once()


def test_sentence_linking_step_run(tmp_path):
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "Hello world.")]
    mock_db.get_word_id_by_lemma.side_effect = lambda lemma: 10 if lemma == "hello" else None

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = SentenceLinkingStep()

    ckpt_file = tmp_path / "sentence_link.json"

    with patch.object(mod_04, "SENTENCE_LINK_CHECKPOINT", ckpt_file), \
         patch.object(mod_04, "Lemmatizer") as mock_lem_cls:
        
        mock_lem = mock_lem_cls.return_value
        mock_lem.lemmatize_text.return_value = [{"lemma": "hello"}]

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_db.insert_word_sentence_map_batch.assert_called_once_with([{"word_id": 10, "sentence_id": 1}])
        assert ckpt_file.exists()
        assert json.loads(ckpt_file.read_text()) == {"last_id": 1}


def test_sentence_linking_deduplication(tmp_path):
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "Hello hello world.")]
    mock_db.get_word_id_by_lemma.side_effect = lambda lemma: 10 if lemma == "hello" else None

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = SentenceLinkingStep()

    ckpt_file = tmp_path / "sentence_link.json"

    with patch.object(mod_04, "SENTENCE_LINK_CHECKPOINT", ckpt_file), \
         patch.object(mod_04, "Lemmatizer") as mock_lem_cls:
        
        mock_lem = mock_lem_cls.return_value
        mock_lem.lemmatize_text.return_value = [{"lemma": "hello"}, {"lemma": "hello"}]

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_db.insert_word_sentence_map_batch.assert_called_once_with([{"word_id": 10, "sentence_id": 1}])



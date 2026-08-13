import json
import pytest
from unittest.mock import MagicMock, patch
import importlib

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus

mod_05 = importlib.import_module("src.pipeline.steps.05_nlp_enrichment")
mod_06 = importlib.import_module("src.pipeline.steps.06_reflex_drills")
mod_07 = importlib.import_module("src.pipeline.steps.07_scenario_trees")
mod_08 = importlib.import_module("src.pipeline.steps.08_ipa_mapping")

NLPEnrichmentStep = mod_05.NLPEnrichmentStep
ReflexDrillsStep = mod_06.ReflexDrillsStep
ScenarioTreesStep = mod_07.ScenarioTreesStep
IPAMappingStep = mod_08.IPAMappingStep


# ---------------------------------------------------------------------------
# NLPEnrichmentStep (05)
# ---------------------------------------------------------------------------

def test_nlp_enrichment_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.return_value = (600,)
    mock_cursor.fetchall.return_value = [
        ("Subject + Verb + Object",),
        ("Subject + Verb + Prepositional Phrase",),
        ("Subject + Auxiliary + Verb + Object",)
    ]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = NLPEnrichmentStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason

    # Test when sentence patterns are missing some patterns
    mock_cursor.fetchall.return_value = [("Subject + Verb + Object",)]
    skip, _ = step.should_skip(ctx)
    assert not skip

    mock_args.force_reset = True
    skip, _ = step.should_skip(ctx)
    assert not skip


def test_nlp_enrichment_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "She drinks hot coffee.")]
    mock_db.insert_collocations_batch.return_value = 1
    mock_db.insert_sentence_patterns_batch.return_value = 3

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = NLPEnrichmentStep()

    with patch.object(mod_05, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_05, "ChunkExtractor") as mock_extractor_cls, \
         patch.object(mod_05, "Translator") as mock_translator_cls:
        
        mock_grader = mock_grader_cls.return_value
        mock_grader.grade_word.return_value = ("C1", 15000)

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.extract_collocations.return_value = [
            {"phrase": "hot coffee", "pos_pattern": "ADJ NOUN"}
        ]

        mock_translator = mock_translator_cls.return_value
        mock_translator.translate_text.return_value = "cà phê nóng"

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 4  # 1 inserted collocation + 3 patterns
        mock_db.insert_collocations_batch.assert_called_once()
        inserted_batch = mock_db.insert_collocations_batch.call_args[0][0]
        assert inserted_batch[0]["cefr_level"] == "C1"  # C1 preserved
        mock_db.insert_sentence_patterns_batch.assert_called_once()
        mock_translator.save_cache.assert_called_once()


# ---------------------------------------------------------------------------
# ReflexDrillsStep (06)
# ---------------------------------------------------------------------------

def test_reflex_drills_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.side_effect = [(100,), (100,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ReflexDrillsStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "already exist" in reason

    executed_sql = mock_cursor.execute.call_args_list[1][0][0]
    assert "JOIN sentences" in executed_sql


def test_reflex_drills_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [
        (1, "Hello.", "Xin chào.", "A1"),
        (2, "Invalid.", "", "A1"),
        (3, "Null sentence.", None, "A1")
    ]
    mock_cursor.fetchone.return_value = (0,)

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ReflexDrillsStep()

    mock_drill = {
        "sentence_id": 1,
        "drill_type": "speed_translation",
        "prompt_text": "Hello.",
        "correct_answer": "Xin chào.",
        "distractors_json": json.dumps(["Tạm biệt"]),
        "target_time_ms": 2500,
    }

    with patch.object(mod_06, "ReflexBuilder") as mock_builder_cls:
        mock_builder = mock_builder_cls.return_value
        mock_builder.build_drill.return_value = mock_drill

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_conn.commit.assert_called()


def test_reflex_drills_rollback_on_failure():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "Hello.", "Xin chào.", "A1")]
    mock_cursor.fetchone.return_value = (0,)

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ReflexDrillsStep()

    with patch.object(mod_06, "ReflexBuilder") as mock_builder_cls:
        mock_builder = mock_builder_cls.return_value
        mock_builder.build_drill.side_effect = RuntimeError("Drill error")

        with pytest.raises(RuntimeError):
            step.run(ctx)

        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# ScenarioTreesStep (07)
# ---------------------------------------------------------------------------

def test_scenario_trees_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.return_value = (5,)

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ScenarioTreesStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "dialogue trees already exist" in reason


def test_scenario_trees_run():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.lastrowid = 1
    mock_cursor.fetchone.return_value = (10,)

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ScenarioTreesStep()

    mock_scenario = {
        "title": "Ordering Coffee",
        "topic": "Food & Drink",
        "cefr_level": "A1",
        "nodes": [
            {
                "node_index": 0,
                "parent_index": None,
                "text_en": "Can I have coffee?",
                "text_vi": "Cho tôi cà phê?",
                "speaker_role": "Customer",
                "choice_label": "Order coffee"
            }
        ]
    }

    with patch.object(mod_07, "ScenarioBuilder") as mock_builder_cls:
        mock_builder = mock_builder_cls.return_value
        mock_builder.build_sample_scenarios.return_value = [mock_scenario]

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_conn.commit.assert_called()
        executed_sqls = [call[0][0] for call in mock_cursor.execute.call_args_list]
        assert any("DELETE FROM dialogue_nodes" in sql for sql in executed_sqls)
        assert any("DELETE FROM dialogue_trees" in sql for sql in executed_sqls)


def test_scenario_trees_rollback_on_failure():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ScenarioTreesStep()

    with patch.object(mod_07, "ScenarioBuilder") as mock_builder_cls:
        mock_builder = mock_builder_cls.return_value
        mock_builder.build_sample_scenarios.side_effect = RuntimeError("Scenario error")

        with pytest.raises(RuntimeError):
            step.run(ctx)

        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# IPAMappingStep (08)
# ---------------------------------------------------------------------------

def test_ipa_mapping_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.return_value = (0,)

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = IPAMappingStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "100% of words already have IPA" in reason


def test_ipa_mapping_run_normal():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "cat", " ", None)]

    mock_args = MagicMock(force_reset=False)
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = IPAMappingStep()

    with patch.object(mod_08, "IPAMapper") as mock_mapper_cls:
        mock_mapper = mock_mapper_cls.return_value
        mock_mapper.get_ipa.return_value = "kæt"

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_conn.commit.assert_called()
        executed_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "WHERE COALESCE(TRIM(ipa_us)" in executed_sql
        assert mock_mapper.get_ipa.call_args_list[0][1]["existing_ipa"] == " "


def test_ipa_mapping_run_force_reset():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchall.return_value = [(1, "cat", "kæt", "kæt")]

    mock_args = MagicMock(force_reset=True)
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = IPAMappingStep()

    with patch.object(mod_08, "IPAMapper") as mock_mapper_cls:
        mock_mapper = mock_mapper_cls.return_value
        mock_mapper.get_ipa.return_value = "kæt"

        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        mock_conn.commit.assert_called()
        executed_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "WHERE" not in executed_sql
        assert mock_mapper.get_ipa.call_args_list[0][1]["existing_ipa"] is None

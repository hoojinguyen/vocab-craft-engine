from pathlib import Path
import importlib
import pytest
from unittest.mock import MagicMock, patch

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus

mod_13 = importlib.import_module("src.pipeline.steps.13_core_pack")
mod_14 = importlib.import_module("src.pipeline.steps.14_sentence_coverage")
mod_15 = importlib.import_module("src.pipeline.steps.15_sqlite_export")

CorePackStep = mod_13.CorePackStep
SentenceCoverageStep = mod_14.SentenceCoverageStep
SQLiteExportStep = mod_15.SQLiteExportStep


def test_core_pack_skip_condition():
    mock_args = MagicMock()
    mock_args.build_core_pack = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    step = CorePackStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "build-core-pack" in reason.lower()


def test_core_pack_should_not_skip_when_flag_set():
    mock_args = MagicMock()
    mock_args.build_core_pack = True

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    step = CorePackStep()

    skip, reason = step.should_skip(ctx)
    assert not skip
    assert reason == ""


def test_core_pack_run():
    with patch.object(mod_13, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_13, "CorePackBuilder") as mock_builder_cls:
        mock_grader = MagicMock()
        mock_grader.freq_dict = {"test": 100}
        mock_grader_cls.return_value = mock_grader

        mock_builder = MagicMock()
        mock_builder.build.return_value = {"selected": 3000, "pass_rate": 0.95}
        mock_builder_cls.return_value = mock_builder

        mock_args = MagicMock()
        mock_args.vi_budget = 1000
        ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)

        step = CorePackStep()
        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 3000
        assert res.metrics["pass_rate"] == 0.95
        mock_builder.build.assert_called_once_with(
            freq_dict={"test": 100},
            ngsl_path=mod_13.NGSL_PATH,
            vi_budget=1000,
        )


from types import SimpleNamespace

def test_sentence_coverage_should_skip():
    ctx = PipelineContext(db_manager=MagicMock(), args=SimpleNamespace(force_reset=False))
    step = SentenceCoverageStep()
    with patch("pathlib.Path.exists", return_value=True):
        skip, reason = step.should_skip(ctx)
    assert not skip


def test_sentence_coverage_run():
    with patch.object(mod_14, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_14, "SentenceFilter") as mock_filter_cls, \
         patch.object(mod_14, "ParallelCorpusParser") as mock_parser_cls:
        mock_filter = MagicMock()
        mock_filter.is_clean_pair.return_value = True
        mock_filter_cls.return_value = mock_filter

        mock_grader = MagicMock()
        mock_grader.grade_sentence.return_value = {"difficulty_score": 0.5, "cefr_level": "B1"}
        mock_grader_cls.return_value = mock_grader

        mock_parser = MagicMock()
        mock_parser.parse_pairs.return_value = [
            {"text_en": "Hello world", "text_vi": "Xin chao the gioi"}
        ]
        mock_parser_cls.return_value = mock_parser

        mock_db = MagicMock()
        mock_db.count_sentences_by_source.return_value = 0
        ctx = PipelineContext(db_manager=mock_db, args=SimpleNamespace(force_reset=False))

        with patch("pathlib.Path.exists", return_value=True):
            step = SentenceCoverageStep()
            res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed > 0
        assert mock_db.insert_sentences_batch.called


def test_sqlite_export_should_skip():
    ctx = PipelineContext(db_manager=MagicMock(), args=MagicMock())
    step = SQLiteExportStep()
    skip, reason = step.should_skip(ctx)
    assert not skip


def test_sqlite_export_run():
    with patch.object(mod_15, "SQLiteExporter") as mock_exporter_cls:
        mock_exporter = MagicMock()
        mock_exporter.optimize_and_package.return_value = {"size_mb": 42.5}
        mock_exporter.benchmark_reflex_query_speed.return_value = 1.23
        mock_exporter_cls.return_value = mock_exporter

        ctx = PipelineContext(db_manager=MagicMock(), args=MagicMock())
        step = SQLiteExportStep()
        res = step.run(ctx)

        assert res.status == StepStatus.SUCCESS
        assert res.items_processed == 1
        assert res.metrics["size_mb"] == 42.5
        assert res.metrics["reflex_speed_ms"] == 1.23


def test_all_15_steps_exported():
    from src.pipeline import steps
    expected_steps = [
        "SchemaInitStep",
        "KaikkiIngestionStep",
        "TatoebaIngestionStep",
        "SentenceLinkingStep",
        "NLPEnrichmentStep",
        "ReflexDrillsStep",
        "ScenarioTreesStep",
        "IPAMappingStep",
        "AudioGenerationStep",
        "PhraseMWEStep",
        "RelationsTopicsStep",
        "VietnameseBackfillStep",
        "CorePackStep",
        "SentenceCoverageStep",
        "SQLiteExportStep",
    ]
    for step_name in expected_steps:
        assert hasattr(steps, step_name)
    assert len(steps.__all__) == 15


def test_core_pack_uses_context_db_path_and_resets_on_force_reset():
    with patch.object(mod_13, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_13, "CorePackBuilder") as mock_builder_cls:
        mock_grader = MagicMock()
        mock_grader.freq_dict = {"test": 100}
        mock_grader_cls.return_value = mock_grader

        mock_builder = MagicMock()
        mock_builder.build.return_value = {"selected": 100, "pass_rate": 1.0}
        mock_builder_cls.return_value = mock_builder

        mock_db = MagicMock()
        custom_path = Path("/tmp/custom_english.db")
        mock_db.db_path = custom_path

        mock_args = MagicMock()
        mock_args.force_reset = True
        mock_args.vi_budget = 500
        ctx = PipelineContext(db_manager=mock_db, args=mock_args)

        step = CorePackStep()
        res = step.run(ctx)

        mock_builder_cls.assert_called_once_with(
            source_db_path=custom_path,
            output_dir=Path(mod_13.OUTPUT_DIR) / "core_pack",
        )
        mock_builder.reset.assert_called_once()
        assert res.status == StepStatus.SUCCESS


def test_sentence_coverage_should_skip_raises_on_db_exception():
    mock_db = MagicMock()
    mock_db.count_sentences_by_source.side_effect = RuntimeError("DB Table Missing")
    ctx = PipelineContext(db_manager=mock_db, args=MagicMock(force_reset=False))
    step = SentenceCoverageStep()
    with pytest.raises(RuntimeError, match="DB Table Missing"):
        with patch("pathlib.Path.exists", return_value=True):
            step.should_skip(ctx)


def test_sentence_coverage_cap_includes_existing_count():
    with patch.object(mod_14, "CEFRGrader") as mock_grader_cls, \
         patch.object(mod_14, "SentenceFilter") as mock_filter_cls, \
         patch.object(mod_14, "ParallelCorpusParser") as mock_parser_cls:
        mock_filter = MagicMock()
        mock_filter.is_clean_pair.return_value = True
        mock_filter_cls.return_value = mock_filter

        mock_grader = MagicMock()
        mock_grader.grade_sentence.return_value = {"difficulty_score": 0.5, "cefr_level": "A1"}
        mock_grader_cls.return_value = mock_grader

        # Simulate 100 pairs available in parser
        pairs = [{"text_en": f"En {i}", "text_vi": f"Vi {i}"} for i in range(100)]
        mock_parser = MagicMock()
        mock_parser.parse_pairs.return_value = pairs
        mock_parser_cls.return_value = mock_parser

        mock_db = MagicMock()
        # Suppose MAX_SENTENCES_PER_CORPUS is 1000, and existing is 995
        mock_db.count_sentences_by_source.return_value = 995
        ctx = PipelineContext(db_manager=mock_db, args=MagicMock(force_reset=False))

        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(mod_14.settings, "MAX_SENTENCES_PER_CORPUS", 1000):
            step = SentenceCoverageStep()
            res = step.run(ctx)

        # Since existing=995 and max=1000, only 5 pairs should be processed/inserted before breaking
        assert res.items_processed == 15

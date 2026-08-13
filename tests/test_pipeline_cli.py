import pytest
from src.pipeline.cli import parse_arguments
from src.pipeline.core.registry import get_default_registry


def test_cli_argument_parser():
    args = parse_arguments(["--steps", "schema_init,phrase_mwe", "--dry-run", "--vi-budget", "500"])
    assert args.steps == "schema_init,phrase_mwe"
    assert args.dry_run is True
    assert args.vi_budget == 500


def test_cli_default_arguments():
    args = parse_arguments([])
    assert args.resume is False
    assert args.tui is True
    assert args.max_retries == 3
    assert args.log_dir == "logs"


def test_cli_new_argument_overrides():
    args = parse_arguments(["--resume", "--no-tui", "--max-retries", "5", "--log-dir", "custom_logs"])
    assert args.resume is True
    assert args.tui is False
    assert args.max_retries == 5
    assert args.log_dir == "custom_logs"



def test_default_registry_loading():
    reg = get_default_registry()
    steps = reg.get_all_steps()
    assert len(steps) == 15
    names = [s.name for s in steps]
    assert names[0] == "schema_init"
    assert names[-1] == "sqlite_export"

    coverage_idx = names.index("sentence_coverage")
    linking_idx = names.index("sentence_linking")
    enrichment_idx = names.index("nlp_enrichment")
    core_pack_idx = names.index("core_pack")

    assert coverage_idx < linking_idx, "sentence_coverage must run before sentence_linking"
    assert coverage_idx < enrichment_idx, "sentence_coverage must run before nlp_enrichment"
    assert core_pack_idx > coverage_idx, "core_pack must run after sentence_coverage"


def test_get_missing_raw_files_handles_empty_file(tmp_path):
    from src.pipeline.cli import get_missing_raw_files
    empty_file = tmp_path / "empty.txt"
    empty_file.touch()
    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("hello")
    missing_file = tmp_path / "missing.txt"

    missing = get_missing_raw_files([empty_file, valid_file, missing_file])
    assert empty_file in missing
    assert missing_file in missing
    assert valid_file not in missing


def test_main_triggers_download_when_raw_files_missing():
    from unittest.mock import patch, MagicMock
    from main import main

    with patch("main.parse_arguments"), \
         patch("main.get_missing_raw_files", return_value=["dummy_missing.txt"]) as mock_get_missing, \
         patch("main.download_all_raw_data") as mock_download, \
         patch("main.DatabaseManager") as mock_db_cls, \
         patch("main.PipelineContext"), \
         patch("main.get_default_registry"), \
         patch("main.PipelineOrchestrator") as mock_orch_cls:

        mock_summary = MagicMock()
        mock_summary.has_failures = False
        mock_orch_cls.return_value.run.return_value = mock_summary

        main()

        mock_get_missing.assert_called_once()
        mock_download.assert_called_once()
        mock_db_cls.return_value.close.assert_called_once()


def test_main_skips_download_when_no_raw_files_missing():
    from unittest.mock import patch, MagicMock
    from main import main

    with patch("main.parse_arguments"), \
         patch("main.get_missing_raw_files", return_value=[]) as mock_get_missing, \
         patch("main.download_all_raw_data") as mock_download, \
         patch("main.DatabaseManager") as mock_db_cls, \
         patch("main.PipelineContext"), \
         patch("main.get_default_registry"), \
         patch("main.PipelineOrchestrator") as mock_orch_cls:

        mock_summary = MagicMock()
        mock_summary.has_failures = False
        mock_orch_cls.return_value.run.return_value = mock_summary

        main()

        mock_get_missing.assert_called_once()
        mock_download.assert_not_called()
        mock_db_cls.return_value.close.assert_called_once()


def test_main_closes_db_manager_in_finally_on_exception():
    from unittest.mock import patch, MagicMock
    from main import main

    with patch("main.parse_arguments"), \
         patch("main.get_missing_raw_files", return_value=[]), \
         patch("main.download_all_raw_data"), \
         patch("main.DatabaseManager") as mock_db_cls, \
         patch("main.PipelineContext"), \
         patch("main.get_default_registry"), \
         patch("main.PipelineOrchestrator") as mock_orch_cls:

        mock_orch_cls.return_value.run.side_effect = RuntimeError("Orchestration error")

        with pytest.raises(RuntimeError, match="Orchestration error"):
            main()

        mock_db_cls.return_value.close.assert_called_once()



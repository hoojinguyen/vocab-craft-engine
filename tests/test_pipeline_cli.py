import pytest
from src.pipeline.cli import parse_arguments
from src.pipeline.core.registry import get_default_registry


def test_cli_argument_parser():
    args = parse_arguments(["--steps", "schema_init,phrase_mwe", "--dry-run", "--vi-budget", "500"])
    assert args.steps == "schema_init,phrase_mwe"
    assert args.dry_run is True
    assert args.vi_budget == 500


def test_default_registry_loading():
    reg = get_default_registry()
    steps = reg.get_all_steps()
    assert len(steps) == 15
    names = [s.name for s in steps]
    assert names[0] == "schema_init"
    assert names[-1] == "sqlite_export"

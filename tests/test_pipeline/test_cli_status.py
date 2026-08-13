import pytest
from src.pipeline.cli import parse_arguments


def test_cli_status_subcommand():
    args = parse_arguments(["status"])
    assert args.command == "status"


def test_cli_reset_subcommand():
    args = parse_arguments(["reset", "--step", "ingest_kaikki"])
    assert args.command == "reset"
    assert args.step == "ingest_kaikki"

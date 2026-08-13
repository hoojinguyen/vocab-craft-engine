from src.pipeline.cli import parse_arguments


def test_cli_export_subcommand():
    args = parse_arguments(["export", "--format", "sqlite"])
    assert args.command == "export"
    assert args.format == "sqlite"

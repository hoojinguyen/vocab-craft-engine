from src.pipeline.cli import parse_arguments


def test_parse_arguments_defaults():
    args = parse_arguments([])
    assert args.dry_run is False
    assert args.force_all is False
    assert args.force_step is None
    assert args.enable is None
    assert args.disable is None


def test_parse_arguments_v2_flags():
    args = parse_arguments([
        "--force-step", "ingest_kaikki,extract_collocations",
        "--force-all",
        "--enable", "generate_audio",
        "--disable", "generate_dialogues",
        "--dry-run"
    ])
    assert args.force_step == "ingest_kaikki,extract_collocations"
    assert args.force_all is True
    assert args.enable == "generate_audio"
    assert args.disable == "generate_dialogues"
    assert args.dry_run is True

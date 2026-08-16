import subprocess
import sys
from pathlib import Path

from src.pipeline.cli import parse_arguments


def test_curriculum_compose_arguments_do_not_select_legacy_pipeline_steps():
    args = parse_arguments(
        [
            "curriculum",
            "compose",
            "--module",
            "module.a0.greetings",
            "--pack-id",
            "a0-a1-pilot",
            "--version",
            "0.1.0",
            "--output-dir",
            "data/output/curriculum/a0-a1-pilot",
        ]
    )

    assert args.command == "curriculum"
    assert args.curriculum_command == "compose"
    assert args.steps is None


def test_curriculum_init_uses_dedicated_database_path(tmp_path):
    from src.learning import cli

    database = tmp_path / "graph.duckdb"
    assert cli.run_curriculum_command(["init", "--db-path", str(database)]) == 0
    assert database.exists()


def test_curriculum_main_dispatch_does_not_import_legacy_steps(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    database = tmp_path / "graph.duckdb"

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "curriculum",
            "init",
            "--db-path",
            str(database),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[nltk_data]" not in result.stdout
    assert "[nltk_data]" not in result.stderr
    assert database.exists()


def test_curriculum_register_source_requires_a_manifest_and_persists_approval(tmp_path):
    from src.learning import cli

    manifest = tmp_path / "source.yaml"
    manifest.write_text(
        "asset_id: human-authored-a0\n"
        "title: Human authored A0 pilot\n"
        "locator: https://example.test/a0\n"
        "asset_version: 2026-08-17\n"
        "sha256: " + ("b" * 64) + "\n"
        "license_id: LicenseRef-Internal\n"
        "license_url: https://example.test/license\n"
        "attribution: VocabCraft editorial team\n"
        "redistribution_allowed: true\n"
        "validation_status: approved\n",
        encoding="utf-8",
    )
    database = tmp_path / "graph.duckdb"

    assert (
        cli.run_curriculum_command(
            ["register-source", "--db-path", str(database), "--manifest", str(manifest)]
        )
        == 0
    )
    store = cli.LearningGraphStore(database)
    assert (
        store.fetch_value(
            "SELECT validation_status FROM source_assets WHERE asset_id = 'human-authored-a0'"
        )
        == "approved"
    )
    store.close()

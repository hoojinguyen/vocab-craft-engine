import hashlib
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


def test_lexical_curriculum_commands_parse_the_controlled_workflow():
    commands = {
        "snapshot-source": [
            "--asset-id",
            "legacy-sqlite",
            "--local-path",
            "reference.db",
            "--retrieved-at",
            "2026-08-17T00:00:00+00:00",
        ],
        "snapshot-lexical-reference": [
            "--reference-db",
            "reference.db",
            "--snapshot-id",
            "snapshot-1",
            "--import-run-id",
            "run-1",
        ],
        "audit-lexical": ["--snapshot-id", "snapshot-1"],
        "review-candidate": [
            "--candidate-id",
            "candidate-1",
            "--decision",
            "approved",
            "--reviewer-id",
            "editor-1",
            "--rationale",
            "Reviewed",
        ],
        "report-lexical": [
            "--validation-run-id",
            "run-1",
            "--output-path",
            "report.json",
        ],
        "compose-lexical": [
            "--validation-run-id",
            "run-1",
            "--pack-id",
            "lexical-a1",
            "--version",
            "0.1.0",
            "--cefr-level",
            "A1",
            "--output-dir",
            "out",
        ],
    }

    for command, command_args in commands.items():
        args = parse_arguments(["curriculum", command, *command_args])
        assert args.curriculum_command == command


def test_lexical_53k_commands_parse_only_explicit_operator_inputs():
    commands = {
        "materialize-lexical-reference": [
            "--reference-db",
            "reference.db",
            "--asset-id",
            "legacy-sqlite",
            "--output-path",
            "data/processed/lexical-53k/snapshots",
        ],
        "import-ranked-lexical-reference": [
            "--reference-db",
            "materialized.db",
            "--snapshot-id",
            "snapshot-1",
            "--import-run-id",
            "import-1",
        ],
        "remediate-lexical": [
            "--snapshot-id",
            "snapshot-1",
            "--validation-run-id",
            "run-1",
            "--resume",
        ],
        "retry-lexical-quarantine": [
            "--validation-run-id",
            "run-1",
            "--input-id",
            "input-1",
        ],
        "report-lexical-remediation": [
            "--validation-run-id",
            "run-1",
            "--output-dir",
            "data/processed/lexical-53k/run-1",
        ],
        "export-verified-lexical": [
            "--validation-run-id",
            "run-1",
            "--version",
            "v1",
            "--output-dir",
            "data/output/lexical-releases/english_dataset_verified_v1",
        ],
    }

    for command, command_args in commands.items():
        args = parse_arguments(["curriculum", command, *command_args])
        assert args.curriculum_command == command


def test_remediation_resume_cli_returns_blocked_contract_exit_code(tmp_path):
    from src.learning import cli

    assert (
        cli.run_curriculum_command(
            [
                "remediate-lexical",
                "--db-path",
                str(tmp_path / "graph.duckdb"),
                "--snapshot-id",
                "snapshot-1",
                "--resume",
            ]
        )
        == 2
    )


def test_verified_lexical_export_cli_requires_explicit_destination_and_prints_manifest(
    graph_catalog, tmp_path, capsys
):
    from src.learning import cli
    from tests.test_learning.test_verified_lexical_pack import (
        seed_resolved_release_graph,
    )

    seeded = seed_resolved_release_graph(graph_catalog)
    database_path = graph_catalog.store._db_path
    graph_catalog.store.close()
    destination = tmp_path / "english_dataset_verified_v1"

    assert (
        cli.run_curriculum_command(
            [
                "export-verified-lexical",
                "--db-path",
                str(database_path),
                "--validation-run-id",
                seeded["validation_run_id"],
                "--version",
                "v1",
                "--output-dir",
                str(destination),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == str(destination / "manifest.json")


def test_snapshot_source_cli_records_a_verified_local_snapshot(tmp_path: Path, capsys):
    from src.learning import cli

    reference_path = tmp_path / "reference.db"
    reference_path.write_bytes(b"verified reference")
    checksum = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    manifest = tmp_path / "source.yaml"
    manifest.write_text(
        "asset_id: legacy-sqlite\n"
        "title: Legacy SQLite fixture\n"
        "locator: https://example.test/legacy.sqlite\n"
        "asset_version: 2026-08-17\n"
        f"sha256: {checksum}\n"
        "license_id: LicenseRef-Test\n"
        "license_url: https://example.test/license\n"
        "attribution: Fixture\n"
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
    assert (
        cli.run_curriculum_command(
            [
                "snapshot-source",
                "--db-path",
                str(database),
                "--asset-id",
                "legacy-sqlite",
                "--local-path",
                str(reference_path),
                "--retrieved-at",
                "2026-08-17T00:00:00+00:00",
            ]
        )
        == 0
    )
    snapshot_id = capsys.readouterr().out.strip().splitlines()[-1]
    store = cli.LearningGraphStore(database)
    assert (
        store.fetch_value(
            "SELECT snapshot_id FROM source_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        )
        == snapshot_id
    )
    store.close()

import argparse

from config.settings import (
    ENVICORPORA_BASIC_EN,
    ENVICORPORA_BASIC_VI,
    ENVICORPORA_TED_LIKE_EN,
    ENVICORPORA_TED_LIKE_VI,
    KAIKKI_JSON_PATH,
    NGSL_PATH,
    OPENSUBTITLES_EN,
    OPENSUBTITLES_VI,
    SUBTLEX_FREQ_PATH,
    TATOEBA_LINKS_PATH,
    TATOEBA_SENTENCES_PATH,
)

REQUIRED_RAW_FILES = [
    KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH,
    TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH,
    NGSL_PATH,
    OPENSUBTITLES_EN,
    OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN,
    ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN,
    ENVICORPORA_BASIC_VI,
]


def get_missing_raw_files(paths) -> list:
    """Returns the subset of raw files that are missing or empty (0 bytes)."""
    return [p for p in paths if not p.exists() or p.stat().st_size == 0]


def parse_arguments(args_list: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Vocab Craft Engine Pipeline Runner (DAG V2)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # status subcommand
    subparsers.add_parser("status", help="Show pipeline steps execution status")

    # reset subcommand
    reset_parser = subparsers.add_parser("reset", help="Reset step execution state")
    reset_parser.add_argument("--step", type=str, help="Specific step to reset")
    reset_parser.add_argument("--all", action="store_true", help="Reset all steps")

    # export subcommand
    export_parser = subparsers.add_parser("export", help="Export dataset")
    export_parser.add_argument(
        "--format",
        type=str,
        choices=["sqlite", "json", "core3000"],
        default="sqlite",
        help="Target export format",
    )

    curriculum_parser = subparsers.add_parser(
        "curriculum", help="Operate the canonical curriculum graph"
    )
    curriculum_subparsers = curriculum_parser.add_subparsers(
        dest="curriculum_command", required=True
    )
    init_parser = curriculum_subparsers.add_parser(
        "init", help="Initialize the separate learning graph database"
    )
    init_parser.add_argument("--db-path")
    register_source = curriculum_subparsers.add_parser(
        "register-source",
        help="Register one source asset from a reviewed YAML manifest",
    )
    register_source.add_argument("--db-path")
    register_source.add_argument("--manifest", required=True)
    snapshot = curriculum_subparsers.add_parser(
        "snapshot-reference", help="Copy legacy words into append-only raw snapshots"
    )
    snapshot.add_argument("--db-path")
    snapshot.add_argument("--reference-db", required=True)
    snapshot.add_argument("--source-id", required=True)
    snapshot.add_argument("--import-run-id", required=True)
    snapshot_source = curriculum_subparsers.add_parser(
        "snapshot-source", help="Register a verified local source snapshot"
    )
    snapshot_source.add_argument("--db-path")
    snapshot_source.add_argument("--asset-id", required=True)
    snapshot_source.add_argument("--local-path", required=True)
    snapshot_source.add_argument("--retrieved-at", required=True)
    snapshot_lexical = curriculum_subparsers.add_parser(
        "snapshot-lexical-reference",
        help="Import a bounded lexical slice from a reference SQLite database",
    )
    snapshot_lexical.add_argument("--db-path")
    snapshot_lexical.add_argument("--reference-db", required=True)
    snapshot_lexical.add_argument("--snapshot-id", required=True)
    snapshot_lexical.add_argument("--import-run-id", required=True)
    audit_lexical = curriculum_subparsers.add_parser(
        "audit-lexical", help="Audit imported lexical bundles"
    )
    audit_lexical.add_argument("--db-path")
    audit_lexical.add_argument("--snapshot-id", required=True)
    materialize_lexical = curriculum_subparsers.add_parser(
        "materialize-lexical-reference",
        help="Materialize an immutable reference before ranked lexical import",
    )
    materialize_lexical.add_argument("--db-path")
    materialize_lexical.add_argument("--reference-db", required=True)
    materialize_lexical.add_argument("--asset-id", required=True)
    materialize_lexical.add_argument("--output-path", required=True)
    import_ranked_lexical = curriculum_subparsers.add_parser(
        "import-ranked-lexical-reference",
        help="Import every rank 1-3500 lexical definition from a materialized snapshot",
    )
    import_ranked_lexical.add_argument("--db-path")
    import_ranked_lexical.add_argument("--reference-db", required=True)
    import_ranked_lexical.add_argument("--snapshot-id", required=True)
    import_ranked_lexical.add_argument("--import-run-id", required=True)
    remediate_lexical = curriculum_subparsers.add_parser(
        "remediate-lexical",
        help="Deterministically validate or quarantine lexical inputs",
    )
    remediate_lexical.add_argument("--db-path")
    remediate_lexical.add_argument("--snapshot-id", required=True)
    remediate_lexical.add_argument("--validation-run-id")
    remediate_lexical.add_argument("--resume", action="store_true")
    remediate_lexical.add_argument("--pilot-size", type=int)
    remediate_lexical.add_argument("--pilot-seed")
    remediate_lexical.add_argument("--batch-size", type=int, default=250)
    remediate_lexical.add_argument("--output-dir")
    retry_lexical = curriculum_subparsers.add_parser(
        "retry-lexical-quarantine", help="Retry one open lexical quarantine case"
    )
    retry_lexical.add_argument("--db-path")
    retry_lexical.add_argument("--validation-run-id", required=True)
    retry_lexical.add_argument("--input-id", required=True)
    report_remediation = curriculum_subparsers.add_parser(
        "report-lexical-remediation",
        help="Write reconciled remediation and internal quarantine artifacts",
    )
    report_remediation.add_argument("--db-path")
    report_remediation.add_argument("--validation-run-id", required=True)
    report_remediation.add_argument("--output-dir", required=True)
    export_verified_lexical = curriculum_subparsers.add_parser(
        "export-verified-lexical",
        help="Atomically publish a fully reviewed lexical dataset release",
    )
    export_verified_lexical.add_argument("--db-path")
    export_verified_lexical.add_argument("--validation-run-id", required=True)
    export_verified_lexical.add_argument("--version", required=True)
    export_verified_lexical.add_argument("--output-dir", required=True)
    review_candidate = curriculum_subparsers.add_parser(
        "review-candidate", help="Record a human decision for a candidate"
    )
    review_candidate.add_argument("--db-path")
    review_candidate.add_argument("--candidate-id", required=True)
    review_candidate.add_argument(
        "--decision", required=True, choices=["approved", "rejected", "quarantined"]
    )
    review_candidate.add_argument("--reviewer-id", required=True)
    review_candidate.add_argument("--rationale", required=True)
    report_lexical = curriculum_subparsers.add_parser(
        "report-lexical", help="Write a deterministic lexical audit report"
    )
    report_lexical.add_argument("--db-path")
    report_lexical.add_argument("--validation-run-id", required=True)
    report_lexical.add_argument("--output-path", required=True)
    compose_lexical = curriculum_subparsers.add_parser(
        "compose-lexical", help="Compose and export an approved lexical pack"
    )
    compose_lexical.add_argument("--db-path")
    compose_lexical.add_argument("--validation-run-id", required=True)
    compose_lexical.add_argument("--pack-id", required=True)
    compose_lexical.add_argument("--version", required=True)
    compose_lexical.add_argument(
        "--cefr-level", required=True, choices=["A1", "A2", "B1"]
    )
    compose_lexical.add_argument("--output-dir", required=True)
    compose = curriculum_subparsers.add_parser(
        "compose", help="Validate and export one approved curriculum module"
    )
    compose.add_argument("--db-path")
    compose.add_argument("--module", required=True)
    compose.add_argument("--pack-id", required=True)
    compose.add_argument("--version", required=True)
    compose.add_argument("--output-dir", required=True)

    # Root flags
    parser.add_argument(
        "--steps", type=str, help="Comma-separated step names to execute."
    )
    parser.add_argument(
        "--skip-steps", type=str, help="Comma-separated step names to skip."
    )
    parser.add_argument(
        "--force-step", type=str, help="Force re-execution of specific step(s)."
    )
    parser.add_argument(
        "--force-all", action="store_true", help="Force re-execution of all steps."
    )
    parser.add_argument(
        "--enable", type=str, help="Comma-separated optional step names to enable."
    )
    parser.add_argument(
        "--disable", type=str, help="Comma-separated step names to disable."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview DAG step execution plan without modifying DB.",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="Force complete database reset and re-ingest everything.",
    )
    parser.add_argument(
        "--skip-dict",
        action="store_true",
        help="Skip Kaikki dictionary ingestion step.",
    )
    parser.add_argument(
        "--vi-budget",
        type=int,
        default=1000,
        help="Max MT translation attempts for Vietnamese backfill.",
    )
    parser.add_argument(
        "--build-core-pack",
        action="store_true",
        help="Build the curated Core 3000 word pack.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume execution from previous failed state.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent worker threads (default: 4).",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        default=False,
        help="Enable Textual TUI dashboard.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_false",
        dest="tui",
        help="Disable Textual TUI dashboard.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum auto-retries per step (default: 3).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="logs",
        help="Directory to store file logs and JSON reports.",
    )

    return parser.parse_args(args_list)

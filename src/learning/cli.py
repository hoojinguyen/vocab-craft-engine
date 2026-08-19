from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from config.settings import LEARNING_GRAPH_DUCKDB_PATH, LEXICAL_53K_RUN_DIR
from src.learning.catalog import SourceCatalog
from src.learning.composer import CurriculumComposer
from src.learning.exporter import CurriculumPackExporter
from src.learning.lexical_audit import LexicalAuditService
from src.learning.models import SourceAssetInput
from src.learning.reference_importer import LegacyReferenceImporter
from src.learning.repository import ContentRepository
from src.learning.store import LearningGraphStore
from src.pipeline.cli import parse_arguments


def run_curriculum_command(argv: list[str] | None = None) -> int:
    args = parse_arguments(["curriculum", *(argv or [])])
    return run_parsed_curriculum_command(args)


def run_parsed_curriculum_command(args: Any) -> int:
    database_path = Path(args.db_path) if args.db_path else LEARNING_GRAPH_DUCKDB_PATH
    store = LearningGraphStore(database_path)
    try:
        store.initialize()
        command = args.curriculum_command
        if command == "init":
            print(database_path)
            return 0
        if command == "register-source":
            source = _load_source_manifest(Path(args.manifest))
            SourceCatalog(store).register_source(source)
            print(source.asset_id)
            return 0
        if command == "snapshot-reference":
            imported = LegacyReferenceImporter(SourceCatalog(store)).import_words(
                Path(args.reference_db), args.source_id, args.import_run_id
            )
            print(imported)
            return 0
        if command == "snapshot-source":
            snapshot_id = SourceCatalog(store).record_source_snapshot(
                args.asset_id,
                Path(args.local_path),
                datetime.fromisoformat(args.retrieved_at),
            )
            print(snapshot_id)
            return 0
        if command == "snapshot-lexical-reference":
            from src.learning.sqlite_reference_importer import (
                SQLiteLexicalReferenceImporter,
            )

            report = SQLiteLexicalReferenceImporter(
                SourceCatalog(store)
            ).import_vertical_slice(
                Path(args.reference_db), args.snapshot_id, args.import_run_id
            )
            print(report.imported_or_existing_raw_records)
            return 0
        if command == "audit-lexical":
            report = LexicalAuditService(store).audit(args.snapshot_id)
            print(report.validation_run_id)
            return 0
        if command == "materialize-lexical-reference":
            from src.learning.sqlite_reference_importer import (
                SQLiteReferenceMaterializer,
            )

            catalog = SourceCatalog(store)
            source_snapshot_id = catalog.record_source_snapshot(
                args.asset_id, Path(args.reference_db), datetime.now(UTC)
            )
            result = SQLiteReferenceMaterializer(
                catalog, Path(args.output_path)
            ).materialize(Path(args.reference_db), source_snapshot_id)
            print(result.snapshot_id)
            print(result.materialized_path)
            return 0
        if command == "import-ranked-lexical-reference":
            from src.learning.lexical_reporting import LexicalRunReporter
            from src.learning.sqlite_reference_importer import (
                SQLiteLexicalReferenceImporter,
            )

            report = SQLiteLexicalReferenceImporter(
                SourceCatalog(store)
            ).import_ranked_definitions(
                Path(args.reference_db), args.snapshot_id, args.import_run_id
            )
            manifest_path = LexicalRunReporter(store).write_input_manifest(
                args.snapshot_id, LEXICAL_53K_RUN_DIR / args.import_run_id
            )
            print(args.import_run_id)
            print(manifest_path)
            return 0
        if command == "remediate-lexical":
            from src.learning.lexical_remediation import LexicalRemediationService
            from src.learning.lexical_sampling import LexicalPilotSampler

            if args.resume and not args.validation_run_id:
                raise ValueError("--resume requires --validation-run-id")
            if args.batch_size <= 0:
                raise ValueError("--batch-size must be positive")
            if args.resume and args.pilot_size is not None:
                raise ValueError(
                    "--resume uses the stored pilot selection; omit --pilot-size"
                )
            output_dir = (
                Path(args.output_dir)
                if args.output_dir
                else LEXICAL_53K_RUN_DIR / (args.validation_run_id or "remediation")
            )
            input_ids = None
            selection_metadata = {"kind": "full_snapshot_v1"}
            if args.resume:
                manifest_path = output_dir / "selection_manifest.json"
                if manifest_path.exists():
                    selection_metadata = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    input_ids = tuple(selection_metadata.get("input_ids", ()))
            if args.pilot_size is not None:
                if not args.validation_run_id:
                    raise ValueError("--pilot-size requires --validation-run-id")
                if not args.pilot_seed:
                    raise ValueError("--pilot-size requires --pilot-seed")
                selection = LexicalPilotSampler(store).select(
                    args.snapshot_id, args.pilot_size, args.pilot_seed
                )
                input_ids = selection.input_ids
                selection_metadata = selection.as_metadata()
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "selection_manifest.json").write_text(
                    json.dumps(selection_metadata, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
            report = LexicalRemediationService(store).run(
                args.snapshot_id,
                validation_run_id=args.validation_run_id,
                input_ids=input_ids,
                selection_metadata=selection_metadata,
                batch_size=args.batch_size,
            )
            if report.completed_at is not None:
                from src.learning.lexical_reporting import LexicalRunReporter

                report_path = LexicalRunReporter(store).write_remediation_report(
                    report.validation_run_id, output_dir
                )
            print(report.validation_run_id)
            if report.completed_at is not None:
                print(report_path)
            return 0
        if command == "retry-lexical-quarantine":
            from src.learning.lexical_remediation import LexicalRemediationService

            LexicalRemediationService(store).retry_input(
                args.validation_run_id, args.input_id
            )
            print(args.input_id)
            return 0
        if command == "report-lexical-remediation":
            from src.learning.lexical_reporting import (
                LexicalRunReporter,
                QuarantineExporter,
            )

            output_dir = Path(args.output_dir)
            report_path = LexicalRunReporter(store).write_remediation_report(
                args.validation_run_id, output_dir
            )
            quarantine = QuarantineExporter(store).export(
                args.validation_run_id, output_dir
            )
            print(report_path)
            print(quarantine.database_path)
            return 0
        if command == "export-verified-lexical":
            from src.learning.verified_lexical_exporter import (
                VerifiedLexicalPackExporter,
            )
            from src.learning.verified_lexical_pack import VerifiedLexicalPackComposer

            pack = VerifiedLexicalPackComposer(store).compose(
                args.validation_run_id, args.version
            )
            result = VerifiedLexicalPackExporter(store).export(
                pack, Path(args.output_dir)
            )
            print(result.manifest_path)
            return 0
        if command == "review-candidate":
            revision_id = ContentRepository(store).review_candidate(
                args.candidate_id,
                args.decision,
                args.reviewer_id,
                args.rationale,
            )
            if revision_id is not None:
                print(revision_id)
            return 0
        if command == "report-lexical":
            _write_lexical_report(
                ContentRepository(store), args.validation_run_id, Path(args.output_path)
            )
            print(args.output_path)
            return 0
        if command == "compose-lexical":
            from src.learning.lexical_exporter import LexicalPackExporter
            from src.learning.lexical_pack import LexicalPackComposer

            repository = ContentRepository(store)
            pack = LexicalPackComposer(repository).compose(
                args.validation_run_id,
                args.pack_id,
                args.version,
                args.cefr_level,
            )
            result = LexicalPackExporter().export(pack, Path(args.output_dir))
            print(result.manifest_path)
            return 0
        if command == "compose":
            repository = ContentRepository(store)
            module_revision_id = repository.get_latest_approved_revision(args.module)
            pack = CurriculumComposer(repository).compose(
                module_revision_id, args.pack_id, args.version
            )
            result = CurriculumPackExporter().export(pack, Path(args.output_dir))
            print(result.manifest_path)
            return 0
        raise ValueError(f"unsupported curriculum command: {command}")
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        store.close()


def _load_source_manifest(path: Path) -> SourceAssetInput:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        document = {}
    asset_version = document.get("asset_version")
    if isinstance(asset_version, (date, datetime)):
        document = {**document, "asset_version": asset_version.isoformat()}
    return SourceAssetInput.model_validate(document)


def _write_lexical_report(
    repository: ContentRepository, validation_run_id: str, output_path: Path
) -> None:
    rows = repository.candidates_for_validation_run(validation_run_id)
    state_counts: dict[str, int] = {}
    for row in rows:
        state = str(row["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
    gate_rows = (
        repository.store.connection()
        .execute(
            """
        SELECT gate_code, count(*)
        FROM candidate_gate_results
        WHERE validation_run_id = ?
        GROUP BY gate_code
        ORDER BY gate_code
        """,
            [validation_run_id],
        )
        .fetchall()
    )
    candidates_needing_review = []
    for row in rows:
        if row["state"] not in {"candidate", "validated"}:
            continue
        gate_codes = (
            repository.store.connection()
            .execute(
                """
            SELECT gate_code
            FROM candidate_gate_results
            WHERE validation_run_id = ? AND candidate_id = ? AND NOT passed
            ORDER BY gate_code
            """,
                [validation_run_id, row["candidate_id"]],
            )
            .fetchall()
        )
        candidates_needing_review.append(
            {
                "candidate_id": row["candidate_id"],
                "state": row["state"],
                "content_type": row["content_type"],
                "payload": repository.candidate_payload(str(row["candidate_id"])),
                "failed_gate_codes": [str(code) for (code,) in gate_codes],
            }
        )
    document = {
        "validation_run_id": validation_run_id,
        "candidate_state_counts": dict(sorted(state_counts.items())),
        "gate_code_counts": {str(code): int(count) for code, count in gate_rows},
        "candidates_needing_review": sorted(
            candidates_needing_review, key=lambda item: str(item["candidate_id"])
        ),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

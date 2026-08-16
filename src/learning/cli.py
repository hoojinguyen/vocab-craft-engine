from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from config.settings import LEARNING_GRAPH_DUCKDB_PATH
from src.learning.catalog import SourceCatalog
from src.learning.composer import CurriculumComposer
from src.learning.exporter import CurriculumPackExporter
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

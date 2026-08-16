from __future__ import annotations

from pathlib import Path

import duckdb

from src.learning.catalog import SourceCatalog


class LegacyReferenceImporter:
    """Copy explicitly allowed legacy word records into graph raw snapshots."""

    def __init__(self, catalog: SourceCatalog) -> None:
        self.catalog = catalog

    def import_words(
        self, legacy_db_path: Path, asset_id: str, import_run_id: str
    ) -> int:
        source_path = Path(legacy_db_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        connection = duckdb.connect(str(source_path), read_only=True)
        try:
            rows = connection.execute(
                "SELECT id, lemma, pos, source FROM words ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        for word_id, lemma, pos, source in rows:
            self.catalog.append_raw_record(
                asset_id=asset_id,
                external_key=f"legacy-word:{word_id}",
                record_type="legacy_word",
                payload={
                    "id": word_id,
                    "lemma": lemma,
                    "pos": pos,
                    "source": source,
                },
                import_run_id=import_run_id,
            )
        return len(rows)

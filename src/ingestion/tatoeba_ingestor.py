"""Tatoeba sentence ingestor."""

import logging
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class TatoebaIngestor:
    def ingest_files(self, db_mgr: DuckDBManager, sentences_path: Path, links_path: Path) -> int:
        if not sentences_path.exists() or not links_path.exists():
            return 0

        # Load sentences
        sentences: dict[int, tuple[str, str]] = {}
        with open(sentences_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    try:
                        sid, lang, text = int(parts[0]), parts[1], parts[2]
                        sentences[sid] = (lang, text)
                    except ValueError:
                        continue

        # Process links
        batch = []
        with open(links_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    try:
                        id1, id2 = int(parts[0]), int(parts[1])
                    except ValueError:
                        continue

                    if id1 in sentences and id2 in sentences:
                        l1, t1 = sentences[id1]
                        l2, t2 = sentences[id2]
                        if l1 == "eng" and l2 == "vie":
                            batch.append({"text_en": t1, "text_vi": t2, "source": "tatoeba"})

        if batch:
            return db_mgr.insert_batch("sentences", batch)
        return 0

"""OPUS OpenSubtitles and EnViCorpora sentence pair ingestor."""

import logging
from pathlib import Path
from config.settings import MAX_SENTENCES_PER_CORPUS
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class OpusIngestor:
    def ingest_pair(self, db_mgr: DuckDBManager, en_path: Path, vi_path: Path, source: str) -> int:
        if not en_path.exists() or not vi_path.exists():
            return 0

        batch = []
        count = 0
        with open(en_path, "r", encoding="utf-8") as f_en, open(vi_path, "r", encoding="utf-8") as f_vi:
            for en_line, vi_line in zip(f_en, f_vi):
                en_text = en_line.strip()
                vi_text = vi_line.strip()
                if not en_text or not vi_text:
                    continue

                words = en_text.split()
                if not (4 <= len(words) <= 25):
                    continue

                batch.append({"text_en": en_text, "text_vi": vi_text, "source": source})
                count += 1

                if len(batch) >= 5000:
                    db_mgr.insert_batch("sentences", batch)
                    batch.clear()

                if count >= MAX_SENTENCES_PER_CORPUS:
                    break

        if batch:
            db_mgr.insert_batch("sentences", batch)

        return count

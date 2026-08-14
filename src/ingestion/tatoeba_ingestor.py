"""Tatoeba sentence and bidirectional translation link ingestor."""

import logging
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TATOEBA_BATCH_SIZE = 20000


class TatoebaIngestor:
    def ingest_files(self, db_mgr: DuckDBManager, sentences_path: Path, links_path: Path) -> int:
        if not sentences_path.exists() or not links_path.exists():
            logger.warning("Tatoeba files missing: %s or %s", sentences_path, links_path)
            return 0

        # Step 1: Load English and Vietnamese sentences only (memory-efficient)
        sentences: dict[int, tuple[str, str]] = {}
        with open(sentences_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    try:
                        sid, lang, text = int(parts[0]), parts[1], parts[2].strip()
                        if lang in ("eng", "vie") and text:
                            sentences[sid] = (lang, text)
                    except ValueError:
                        continue

        logger.info("Loaded %d Tatoeba sentences (eng + vie)", len(sentences))

        # Step 2: Process links in both directions (eng -> vie and vie -> eng)
        batch = []
        seen_texts: set[str] = set()
        count = 0

        with open(links_path, "r", encoding="utf-8", errors="replace") as f:
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

                        text_en, text_vi = None, None
                        if l1 == "eng" and l2 == "vie":
                            text_en, text_vi = t1, t2
                        elif l1 == "vie" and l2 == "eng":
                            text_en, text_vi = t2, t1

                        if text_en and text_vi and text_en not in seen_texts:
                            words = text_en.split()
                            if 4 <= len(words) <= 25:
                                seen_texts.add(text_en)
                                batch.append({
                                    "text_en": text_en,
                                    "text_vi": text_vi,
                                    "source": "tatoeba",
                                })
                                count += 1

                                if len(batch) >= TATOEBA_BATCH_SIZE:
                                    db_mgr.insert_batch_fast("sentences", batch)
                                    batch.clear()

        if batch:
            db_mgr.insert_batch_fast("sentences", batch)

        logger.info("Ingested %d Tatoeba sentence pairs", count)
        return count

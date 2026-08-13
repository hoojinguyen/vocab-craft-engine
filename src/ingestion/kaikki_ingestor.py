"""Kaikki Wiktionary JSON stream ingestor using orjson."""

import logging
from pathlib import Path
from typing import Any, Dict, List
import orjson

from src.db.duckdb_manager import DuckDBManager
from src.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

KAIKKI_BATCH_SIZE = 20000


class KaikkiIngestor(BaseIngestor):
    def ingest(self, db_mgr: DuckDBManager, source_path: Path) -> int:
        if not source_path.exists():
            logger.warning("Kaikki source file not found at %s", source_path)
            return 0

        words_batch: List[Dict[str, Any]] = []
        defs_batch: List[Dict[str, Any]] = []
        word_count = 0

        with open(source_path, "rb") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = orjson.loads(line)
                except Exception:
                    continue

                if data.get("lang") != "English":
                    continue

                lemma = data.get("word")
                pos = data.get("pos")
                if not lemma or not pos:
                    continue

                ipa_us = None
                ipa_uk = None
                sounds = data.get("sounds", [])
                for s in sounds:
                    ipa = s.get("ipa")
                    if ipa:
                        if "US" in s.get("tags", []):
                            ipa_us = ipa
                        elif "UK" in s.get("tags", []):
                            ipa_uk = ipa
                        elif not ipa_us:
                            ipa_us = ipa

                words_batch.append({
                    "lemma": lemma.lower(),
                    "pos": pos.lower(),
                    "ipa_uk": ipa_uk,
                    "ipa_us": ipa_us,
                    "source": "kaikki",
                })

                senses = data.get("senses", [])
                for sense in senses:
                    glosses = sense.get("glosses", [])
                    def_text = glosses[0] if glosses else None
                    if not def_text:
                        continue

                    examples = sense.get("examples", [])
                    ex_text = examples[0].get("text") if examples else None

                    defs_batch.append({
                        "word_id": word_count + len(words_batch),
                        "definition_en": def_text,
                        "example": ex_text,
                        "source": "kaikki",
                    })

                if len(words_batch) >= KAIKKI_BATCH_SIZE:
                    db_mgr.insert_batch("words", words_batch)
                    word_count += len(words_batch)
                    words_batch.clear()

                if len(defs_batch) >= KAIKKI_BATCH_SIZE:
                    db_mgr.insert_batch("definitions", defs_batch)
                    defs_batch.clear()

        if words_batch:
            db_mgr.insert_batch("words", words_batch)
            word_count += len(words_batch)
        if defs_batch:
            db_mgr.insert_batch("definitions", defs_batch)

        return word_count

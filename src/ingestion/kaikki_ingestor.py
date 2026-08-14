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

        conn = db_mgr.get_connection()
        existing = conn.execute("SELECT lemma, pos, id FROM words").fetchall()
        lemma_pos_to_id: Dict[Tuple[str, str], int] = {(row[0], row[1]): row[2] for row in existing}
        next_word_id = max(lemma_pos_to_id.values(), default=0) + 1

        words_batch: List[Dict[str, Any]] = []
        defs_batch: List[Dict[str, Any]] = []
        new_word_count = 0

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

                raw_lemma = data.get("word")
                raw_pos = data.get("pos")
                if not raw_lemma or not raw_pos:
                    continue

                lemma = raw_lemma.lower()
                pos = raw_pos.lower()
                key = (lemma, pos)

                if key not in lemma_pos_to_id:
                    word_id = next_word_id
                    next_word_id += 1
                    lemma_pos_to_id[key] = word_id

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
                        "id": word_id,
                        "lemma": lemma,
                        "pos": pos,
                        "ipa_uk": ipa_uk,
                        "ipa_us": ipa_us,
                        "source": "kaikki",
                    })
                    new_word_count += 1
                else:
                    word_id = lemma_pos_to_id[key]

                senses = data.get("senses", [])
                for sense in senses:
                    glosses = sense.get("glosses", [])
                    def_text = glosses[0] if glosses else None
                    if not def_text:
                        continue

                    examples = sense.get("examples", [])
                    ex_text = examples[0].get("text") if examples else None

                    defs_batch.append({
                        "word_id": word_id,
                        "definition_en": def_text,
                        "example": ex_text,
                        "source": "kaikki",
                    })

                if len(words_batch) >= KAIKKI_BATCH_SIZE or len(defs_batch) >= KAIKKI_BATCH_SIZE:
                    if words_batch:
                        db_mgr.insert_batch("words", words_batch)
                        words_batch.clear()
                    if defs_batch:
                        db_mgr.insert_batch("definitions", defs_batch)
                        defs_batch.clear()

        if words_batch:
            db_mgr.insert_batch("words", words_batch)
            words_batch.clear()
        if defs_batch:
            db_mgr.insert_batch("definitions", defs_batch)
            defs_batch.clear()

        return new_word_count

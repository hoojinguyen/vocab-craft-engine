"""Kaikki Wiktionary JSON stream ingestor using orjson."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import orjson
import pyarrow as pa

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
        seen_in_batch: Set[Tuple[str, str]] = set()

        words_batch: List[Dict[str, Any]] = []
        pending_defs: List[Tuple[Tuple[str, str], str, str | None]] = []
        new_word_count = 0

        def flush_batch():
            nonlocal new_word_count
            if words_batch:
                db_mgr.insert_batch_fast("words", words_batch)
                new_word_count += len(words_batch)
                words_batch.clear()
                seen_in_batch.clear()

            if pending_defs:
                missing_keys: Set[Tuple[str, str]] = {
                    key for key, _, _ in pending_defs if key not in lemma_pos_to_id
                }
                if missing_keys:
                    missing_list = [{"lemma": k[0], "pos": k[1]} for k in missing_keys]
                    arrow_tbl = pa.Table.from_pylist(missing_list)
                    with db_mgr._lock:
                        conn_local = db_mgr.get_connection()
                        conn_local.register("_tmp_missing_words", arrow_tbl)
                        resolved = conn_local.execute(
                            "SELECT w.lemma, w.pos, w.id FROM words w "
                            "JOIN _tmp_missing_words m ON w.lemma = m.lemma AND w.pos = m.pos"
                        ).fetchall()
                        conn_local.unregister("_tmp_missing_words")
                        for r in resolved:
                            lemma_pos_to_id[(r[0], r[1])] = r[2]

                defs_batch: List[Dict[str, Any]] = []
                for key, def_text, ex_text in pending_defs:
                    word_id = lemma_pos_to_id.get(key)
                    if word_id is not None:
                        defs_batch.append({
                            "word_id": word_id,
                            "definition_en": def_text,
                            "example": ex_text,
                            "source": "kaikki",
                        })

                if defs_batch:
                    db_mgr.insert_batch_fast("definitions", defs_batch)
                pending_defs.clear()

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

                if key not in lemma_pos_to_id and key not in seen_in_batch:
                    seen_in_batch.add(key)
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
                        "lemma": lemma,
                        "pos": pos,
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

                    pending_defs.append((key, def_text, ex_text))

                if len(words_batch) >= KAIKKI_BATCH_SIZE or len(pending_defs) >= KAIKKI_BATCH_SIZE:
                    flush_batch()

        flush_batch()
        return new_word_count


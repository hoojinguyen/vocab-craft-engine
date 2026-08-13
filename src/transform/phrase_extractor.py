"""Phrase and Multi-Word Expression Extractor."""

import logging
import re
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

COMMON_PHRASAL_VERBS = ["break down", "give up", "take off", "look for", "carry out"]


class PhraseExtractor:
    def extract(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        sentences = conn.execute("SELECT id, text_en FROM sentences").fetchall()

        phrases_batch = []
        links_batch = []
        phrase_id_map = {}

        for sid, text in sentences:
            text_lower = text.lower()
            for pv in COMMON_PHRASAL_VERBS:
                if re.search(r'\b' + re.escape(pv) + r'\b', text_lower):
                    if pv not in phrase_id_map:
                        phrases_batch.append({
                            "phrase": pv,
                            "phrase_type": "phrasal_verb",
                            "definition_en": f"Phrasal verb: {pv}",
                        })
                        phrase_id_map[pv] = len(phrases_batch)

                    pid = phrase_id_map[pv]
                    links_batch.append({"phrase_id": pid, "sentence_id": sid, "rank": 1})

        if phrases_batch:
            db_mgr.insert_batch("phrases", phrases_batch)
        if links_batch:
            db_mgr.insert_batch("phrase_sentences", links_batch)

        return len(phrases_batch)

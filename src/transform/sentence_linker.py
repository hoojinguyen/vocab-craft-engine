"""Word-Sentence Linker Transform."""

import logging
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class SentenceLinker:
    def link(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        words = conn.execute("SELECT id, lemma FROM words").fetchall()
        sentences = conn.execute("SELECT id, text_en FROM sentences").fetchall()

        word_map = {lemma.lower(): wid for wid, lemma in words}
        batch = []

        for sid, text in sentences:
            tokens = set(text.lower().split())
            for token in tokens:
                clean_token = token.strip(".,!?\"'")
                if clean_token in word_map:
                    batch.append({"word_id": word_map[clean_token], "sentence_id": sid})

        if batch:
            return db_mgr.insert_batch("word_sentences", batch)
        return 0

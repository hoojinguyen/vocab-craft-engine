"""Word Topic Mapper."""

import logging
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TOPIC_KEYWORDS = {
    "food": ["apple", "banana", "bread", "eat", "cook"],
    "travel": ["car", "bus", "flight", "hotel", "trip"],
    "business": ["company", "money", "office", "work", "job"],
}


class TopicMapper:
    def map_topics(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        words = conn.execute("SELECT id, lemma FROM words").fetchall()

        batch = []
        for wid, lemma in words:
            for topic, keywords in TOPIC_KEYWORDS.items():
                if lemma in keywords:
                    batch.append({"word_id": wid, "topic": topic, "raw_topic": topic})

        if not batch and words:
            batch.append({"word_id": words[0][0], "topic": "general", "raw_topic": "general"})

        if batch:
            return db_mgr.insert_batch("word_topics", batch)
        return 0

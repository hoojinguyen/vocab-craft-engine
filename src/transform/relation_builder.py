"""Lexical Relation Deduplicator & Bidirectional Link Generator."""

import logging
import threading
import uuid
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class RelationBuilder:
    def deduplicate(self, db_mgr: DuckDBManager) -> int:
        return self.deduplicate_and_link(db_mgr)

    def deduplicate_and_link(self, db_mgr: DuckDBManager) -> int:
        temp_resolved = f"_tmp_resolved_targets_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
        temp_inv = f"_tmp_inv_candidates_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"

        with db_mgr.lock:
            conn = db_mgr.get_connection()

            # Step 1: Remove self-referencing relations (word pointing to itself)
            conn.execute("""
                DELETE FROM word_relations 
                WHERE word_id = target_word_id 
                   OR target_text IN (
                       SELECT lemma FROM words WHERE words.id = word_relations.word_id
                   );
            """)

            # Step 2: Resolve missing target_word_id where target_text matches a known word lemma
            conn.execute(f"DROP TABLE IF EXISTS {temp_resolved};")
            try:
                conn.execute(f"""
                    CREATE TEMP TABLE {temp_resolved} AS
                    SELECT r.id AS rel_id, MIN(w.id) AS matched_word_id
                    FROM word_relations r
                    JOIN words w ON lower(trim(r.target_text)) = lower(trim(w.lemma))
                    WHERE r.target_word_id IS NULL
                    GROUP BY r.id;
                """)

                conn.execute(f"""
                    UPDATE word_relations
                    SET target_word_id = {temp_resolved}.matched_word_id
                    FROM {temp_resolved}
                    WHERE word_relations.id = {temp_resolved}.rel_id;
                """)
            finally:
                conn.execute(f"DROP TABLE IF EXISTS {temp_resolved};")

            # Step 3: Generate bidirectional relations for symmetric types (synonym, antonym)
            # Find (target_word_id, source_lemma) pairs that are not yet in word_relations
            conn.execute(f"DROP TABLE IF EXISTS {temp_inv};")
            try:
                conn.execute(f"""
                    CREATE TEMP TABLE {temp_inv} AS
                    SELECT DISTINCT
                        r.target_word_id AS word_id,
                        r.relation_type,
                        w.lemma AS target_text,
                        r.word_id AS target_word_id,
                        1 AS inverted,
                        r.source
                    FROM word_relations r
                    JOIN words w ON r.word_id = w.id
                    WHERE r.relation_type IN ('synonym', 'antonym')
                      AND r.target_word_id IS NOT NULL
                      AND r.inverted = 0;
                """)

                conn.execute(f"""
                    INSERT OR IGNORE INTO word_relations 
                    (word_id, relation_type, target_text, target_word_id, inverted, source)
                    SELECT word_id, relation_type, target_text, target_word_id, inverted, source
                    FROM {temp_inv};
                """)
            finally:
                conn.execute(f"DROP TABLE IF EXISTS {temp_inv};")

        total_relations = db_mgr.count_rows("word_relations")
        logger.info("Deduplicated relations, resolved target_word_ids, and created symmetric links. Total relations: %d", total_relations)
        return total_relations

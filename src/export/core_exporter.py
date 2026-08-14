"""
Core 3000 SQLite Bundle Exporter.

Extracts the top 3,000 high-frequency headwords from DuckDB staging along with
their definitions, relations, topics, phrases, and linked sentences into a standalone
optimized core_3000.db SQLite database.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Dict

from src.db.duckdb_manager import DuckDBManager
from src.export.schema import SQLITE_INDEXES, SQLITE_SCHEMA

logger = logging.getLogger(__name__)


class CoreExporter:
    """Exports a curated top 3,000 core vocabulary SQLite database."""

    def export_core_bundle(
        self,
        db_mgr: DuckDBManager,
        target_path: Path,
        core_limit: int = 3000,
    ) -> int:
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists():
            target_file.unlink()

        logger.info("Exporting Core %d bundle to %s", core_limit, target_file)

        s_conn = sqlite3.connect(str(target_file))
        s_cursor = s_conn.cursor()

        # Performance pragmas
        s_cursor.execute("PRAGMA synchronous = OFF;")
        s_cursor.execute("PRAGMA journal_mode = MEMORY;")
        s_cursor.execute("PRAGMA temp_store = MEMORY;")
        s_cursor.execute("PRAGMA foreign_keys = OFF;")

        # Create schema
        s_cursor.executescript(SQLITE_SCHEMA)
        s_conn.commit()

        d_conn = db_mgr.get_connection()

        # Step 1: Select top core word IDs
        core_word_rows = d_conn.execute(f"""
            SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source
            FROM words
            ORDER BY 
                CASE WHEN frequency_rank IS NOT NULL THEN frequency_rank ELSE 999999 END ASC,
                id ASC
            LIMIT {core_limit}
        """).fetchall()

        if not core_word_rows:
            logger.warning("No words found in staging DB for core bundle export")
            s_conn.close()
            return 0

        core_word_ids = [r[0] for r in core_word_rows]
        id_set_str = ", ".join(str(wid) for wid in core_word_ids)

        s_cursor.executemany("""
            INSERT INTO words (id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, core_word_rows)

        # Step 2: Export definitions for core words
        defs_rows = d_conn.execute(f"""
            SELECT id, word_id, definition_en, definition_vi, example, source
            FROM definitions
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT INTO definitions (id, word_id, definition_en, definition_vi, example, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, defs_rows)

        # Step 3: Export word-sentence links and sentences
        ws_rows = d_conn.execute(f"""
            SELECT word_id, sentence_id
            FROM word_sentences
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT OR IGNORE INTO word_sentences (word_id, sentence_id)
            VALUES (?, ?)
        """, ws_rows)

        core_sent_ids = list({r[1] for r in ws_rows})
        if core_sent_ids:
            sent_set_str = ", ".join(str(sid) for sid in core_sent_ids)
            sent_rows = d_conn.execute(f"""
                SELECT id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source
                FROM sentences
                WHERE id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO sentences (id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, sent_rows)

            # Export reflex drills for core sentences
            drills_rows = d_conn.execute(f"""
                SELECT id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms
                FROM reflex_drills
                WHERE sentence_id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO reflex_drills (id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, drills_rows)

        # Step 4: Export word_topics and word_relations
        topics_rows = d_conn.execute(f"""
            SELECT word_id, topic, raw_topic
            FROM word_topics
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic)
            VALUES (?, ?, ?)
        """, topics_rows)

        rel_rows = d_conn.execute(f"""
            SELECT id, word_id, relation_type, target_text, target_word_id, inverted, source
            FROM word_relations
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT OR IGNORE INTO word_relations (id, word_id, relation_type, target_text, target_word_id, inverted, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rel_rows)

        # Step 5: Export all dialogue trees and nodes
        tree_rows = d_conn.execute("SELECT id, title, topic, cefr_level, root_node_id FROM dialogue_trees").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_trees (id, title, topic, cefr_level, root_node_id) VALUES (?, ?, ?, ?, ?)", tree_rows)

        node_rows = d_conn.execute("SELECT id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id FROM dialogue_nodes").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_nodes (id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id) VALUES (?, ?, ?, ?, ?, ?)", node_rows)

        s_conn.commit()

        # Step 6: Create performance indexes
        s_cursor.executescript(SQLITE_INDEXES)

        # Step 7: Populate metadata
        now_str = datetime.now(timezone.utc).isoformat()
        metadata_entries = [
            ("version", "2.0"),
            ("bundle_type", "core_3000"),
            ("build_timestamp", now_str),
            ("core_words_count", str(len(core_word_rows))),
            ("definitions_count", str(len(defs_rows))),
            ("sentences_count", str(len(core_sent_ids))),
        ]
        s_cursor.executemany("INSERT OR REPLACE INTO dataset_metadata (key, value) VALUES (?, ?)", metadata_entries)
        s_conn.commit()

        # Final maintenance
        s_cursor.execute("PRAGMA foreign_keys = ON;")
        s_cursor.execute("PRAGMA journal_mode = WAL;")
        s_cursor.execute("PRAGMA optimize;")
        s_conn.close()

        logger.info("Successfully created Core %d SQLite database (%d words)", core_limit, len(core_word_rows))
        return len(core_word_rows)

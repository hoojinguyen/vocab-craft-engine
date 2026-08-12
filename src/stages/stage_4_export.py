"""Stage 4: Export — DuckDB staging to SQLite production DB via DuckDB SQLite Extension."""

import logging
import sqlite3
from src.pipeline.context import PipelineContext
from src.db.sqlite_manager import SQLiteBulkWriter

logger = logging.getLogger(__name__)


def stage_4_export(ctx: PipelineContext):
    """Bulk export from DuckDB to SQLite via DuckDB ATTACH (TYPE SQLITE)."""
    db = ctx.duckdb_conn
    conn = db.conn if hasattr(db, "conn") else db

    # 1. Initialize SQLite schema using SQLiteBulkWriter
    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()
    writer.close()

    # 2. Attach SQLite DB in DuckDB and copy tables in C++ vectorized engine
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    conn.execute(f"ATTACH '{ctx.sqlite_path}' AS sqlite_target (TYPE SQLITE);")

    try:
        conn.execute("""
            INSERT INTO sqlite_target.words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level)
            SELECT lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.definitions (word_id, definition_en, definition_vi, example, source)
            SELECT w.id, d.definition_en, d.definition_vi, d.example, d.source
            FROM raw_definitions d
            JOIN raw_words w ON w.lemma = d.lemma;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.sentences (text_en, text_vi, difficulty_score, cefr_level, source)
            SELECT text_en, text_vi, difficulty_score, cefr_level, source FROM raw_sentences;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.phrases (phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa)
            SELECT phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa FROM raw_phrases;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.collocations (phrase, meaning_vi, pos_pattern, cefr_level)
            SELECT phrase, meaning_vi, pos_pattern, cefr_level FROM collocations;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.word_relations (word_id, relation_type, target_text, target_word_id, inverted, source)
            SELECT w.id, r.relation_type, r.target_text, tw.id, r.inverted, r.source
            FROM raw_relations r
            JOIN raw_words w ON w.lemma = r.lemma
            LEFT JOIN raw_words tw ON tw.lemma = r.target_text;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.word_topics (word_id, topic, raw_topic)
            SELECT word_id, topic, raw_topic FROM word_topics;
        """)

        conn.execute("""
            INSERT INTO sqlite_target.reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
            SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json, COALESCE(target_time_ms, 2500) FROM reflex_drills;
        """)
    finally:
        conn.execute("DETACH sqlite_target;")

    # 3. Create indexes & verify foreign keys
    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.create_indexes()
    writer.optimize()

    violations = writer.conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        logger.warning("[Stage 4] Foreign key violations: %d", len(violations))

    size_mb = ctx.sqlite_path.stat().st_size / 1e6 if ctx.sqlite_path.exists() else 0
    logger.info("[Stage 4] Vectorized Export complete. DB size: %.1f MB", size_mb)
    writer.close()

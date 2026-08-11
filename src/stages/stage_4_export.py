"""Stage 4: Export — DuckDB staging to SQLite production DB."""

import logging
from src.pipeline.context import PipelineContext
from src.db.sqlite_manager import SQLiteBulkWriter

logger = logging.getLogger(__name__)


def stage_4_export(ctx: PipelineContext):
    """Bulk export from DuckDB to SQLite with WAL optimization."""
    db = ctx.duckdb_conn

    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()

    _export_words(ctx, db, writer)
    _export_definitions(ctx, db, writer)
    _export_sentences(ctx, db, writer)
    _export_collocations(ctx, db, writer)
    _export_phrases(ctx, db, writer)
    _export_relations(ctx, db, writer)
    _export_topics(ctx, db, writer)
    _export_reflex_drills(ctx, db, writer)

    writer.create_indexes()
    writer.optimize()

    violations = writer.conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        logger.warning("[Stage 4] Foreign key violations: %d", len(violations))

    size_mb = ctx.sqlite_path.stat().st_size / 1e6 if ctx.sqlite_path.exists() else 0
    logger.info("[Stage 4] Export complete. DB size: %.1f MB", size_mb)
    writer.close()


def _export_words(ctx, db, writer):
    words = db.query("SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words").fetchall()
    writer.insert_words([
        {"lemma": r[1], "pos": r[2], "ipa_uk": r[3], "ipa_us": r[4],
         "frequency_rank": r[5], "cefr_level": r[6]}
        for r in words
    ], commit_every=10)
    logger.info("[Stage 4] Words: %d", len(words))


def _export_definitions(ctx, db, writer):
    if not ctx.lemma_cache:
        return
    defs = db.query("SELECT lemma, definition_en, definition_vi, example, source FROM raw_definitions").fetchall()
    rows = []
    for lemma, def_en, def_vi, example, source in defs:
        word_id = ctx.lemma_cache.get(lemma)
        if word_id:
            rows.append({"word_id": word_id, "definition_en": def_en,
                          "definition_vi": def_vi, "example": example, "source": source})
    writer.insert_definitions(rows, commit_every=10)
    logger.info("[Stage 4] Definitions: %d", len(rows))


def _export_sentences(ctx, db, writer):
    sentences = db.query("SELECT text_en, text_vi, difficulty_score, cefr_level, source FROM raw_sentences").fetchall()
    writer.insert_sentences([
        {"text_en": r[0], "text_vi": r[1], "difficulty_score": r[2],
         "cefr_level": r[3], "audio_path": None, "source": r[4]}
        for r in sentences
    ], commit_every=10)
    logger.info("[Stage 4] Sentences: %d", len(sentences))


def _export_collocations(ctx, db, writer):
    collocs = db.query("SELECT phrase, meaning_vi, pos_pattern, cefr_level FROM collocations").fetchall()
    writer.insert_collocations([
        {"phrase": r[0], "meaning_vi": r[1], "pos_pattern": r[2], "cefr_level": r[3]}
        for r in collocs
    ], commit_every=10)


def _export_phrases(ctx, db, writer):
    phrases = db.query("SELECT phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa FROM raw_phrases").fetchall()
    writer.insert_phrases([{
        "phrase": r[0], "phrase_type": r[1], "pos": r[2], "cefr_level": r[3],
        "definition_en": r[4], "definition_vi": r[5], "ipa": r[6],
        "difficulty_score": None, "audio_std": None, "audio_fast": None, "audio_status": "ok"
    } for r in phrases], commit_every=10)


def _export_relations(ctx, db, writer):
    if not ctx.lemma_cache:
        return
    rels = db.query(
        "SELECT lemma, relation_type, target_text, inverted, source FROM raw_relations"
    ).fetchall()
    rows = []
    for lemma, rel_type, target_text, inverted, source in rels:
        word_id = ctx.lemma_cache.get(lemma)
        if word_id is None:
            continue
        target_id = ctx.lemma_cache.get(target_text)
        rows.append({
            "word_id": word_id, "relation_type": rel_type,
            "target_text": target_text, "target_word_id": target_id,
            "inverted": inverted, "source": source,
        })
    writer.insert_word_relations(rows, commit_every=10)


def _export_topics(ctx, db, writer):
    topics = db.query("SELECT word_id, topic, raw_topic FROM word_topics").fetchall()
    writer.insert_word_topics([
        {"word_id": r[0], "topic": r[1], "raw_topic": r[2]}
        for r in topics
    ], commit_every=10)


def _export_reflex_drills(ctx, db, writer):
    drills = db.query("SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms FROM reflex_drills").fetchall()
    writer.insert_reflex_drills([{
        "sentence_id": r[0], "drill_type": r[1], "prompt_text": r[2],
        "correct_answer": r[3], "distractors_json": r[4], "target_time_ms": r[5] or 2500
    } for r in drills], commit_every=10)

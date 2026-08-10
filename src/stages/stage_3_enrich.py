"""Stage 3: Enrich — Vietnamese translation, reflex drills, audio generation."""

import logging
import time
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_3_enrich(ctx: PipelineContext):
    """Async enrichment: translations, drills, audio."""
    _backfill_translations(ctx)
    _generate_reflex_drills(ctx)
    _build_dialogue_scenarios(ctx)
    logger.info("[Stage 3] Enrich complete.")


def _backfill_translations(ctx: PipelineContext):
    """Backfill all missing Vietnamese translations."""
    from src.nlp.translator_hybrid import HybridTranslator
    translator = HybridTranslator()
    db = ctx.duckdb_conn

    null_colls = db.query(
        "SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = ''"
    ).fetchall()
    _translate_and_update(db, "collocations", "id", "meaning_vi", null_colls, translator)
    logger.info("[Stage 3] Collocation translations: %d", len(null_colls))


def _translate_and_update(db, table, id_col, target_col, rows, translator, batch_size: int = 100):
    if not rows:
        return
    conn = db.connect()
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        updates = []
        for row_id, text in batch:
            vi = translator.translate(text)
            if vi:
                updates.append((vi, row_id))
        if updates:
            conn.executemany(
                f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?",
                updates,
            )
            conn.commit()
        time.sleep(0.1)


def _generate_reflex_drills(ctx: PipelineContext):
    """Generate reflex drill cards for sentences."""
    from src.nlp.reflex_builder import ReflexBuilder
    db = ctx.duckdb_conn
    sentences = db.query("SELECT id, text_en, text_vi, cefr_level FROM raw_sentences").fetchall()
    if not sentences:
        return
    pool = [{"id": r[0], "text_en": r[1], "text_vi": r[2], "cefr_level": r[3]} for r in sentences]
    builder = ReflexBuilder(sentence_pool=pool)
    for sent in pool:
        drill = builder.build_drill(sent)
        db.insert_rows("reflex_drills", [drill])
    logger.info("[Stage 3] Reflex drills: %d", db.row_count("reflex_drills"))


def _build_dialogue_scenarios(ctx: PipelineContext):
    """Build dialogue trees."""
    from src.nlp.scenario_builder import ScenarioBuilder
    builder = ScenarioBuilder()
    scenarios = builder.build_sample_scenarios()
    db = ctx.duckdb_conn
    for sc in scenarios:
        db.execute(
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (?, ?, ?)",
            (sc["title"], sc["topic"], sc["cefr_level"]),
        )
    logger.info("[Stage 3] Dialogue scenarios: %d", db.row_count("dialogue_trees"))

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
    """Build and mine interactive dialogue trees and populate staging tables."""
    from src.nlp.scenario_builder import ScenarioBuilder

    db = ctx.duckdb_conn
    conn = db.conn if hasattr(db, "conn") else db
    builder = ScenarioBuilder()

    scenarios = builder.mine_dialogue_trees(db, max_trees_per_topic=5)

    node_id_counter = 1
    for sc in scenarios:
        tree_res = conn.execute(
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (?, ?, ?) RETURNING id",
            (sc["title"], sc["topic"], sc["cefr_level"]),
        ).fetchone()

        tree_id = tree_res[0] if tree_res else 1

        index_to_id = {}
        for node in sc["nodes"]:
            parent_id = index_to_id.get(node["parent_index"]) if node.get("parent_index") is not None else None

            conn.execute(
                """INSERT INTO dialogue_nodes (id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (node_id_counter, tree_id, parent_id, node.get("choice_label"), node["speaker_role"], node.get("sentence_id")),
            )
            index_to_id[node["node_index"]] = node_id_counter
            node_id_counter += 1

    logger.info("[Stage 3] Dialogue trees mined: %d, nodes: %d", db.row_count("dialogue_trees"), db.row_count("dialogue_nodes"))

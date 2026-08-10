"""Stage 2: Transform — CEFR grading, lemmatization, collocations."""

import logging
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_2_transform(ctx: PipelineContext):
    """Apply transforms to DuckDB staging data."""
    db = ctx.duckdb_conn
    _apply_cefr_grading(ctx, db)
    _build_lemma_cache(ctx, db)
    _link_word_sentences(ctx, db)
    _extract_collocations(ctx, db)
    _build_inverse_relations(db)
    _map_topics(ctx, db)
    logger.info("[Stage 2] Transform complete.")


def _apply_cefr_grading(ctx: PipelineContext, db):
    """Apply CEFR grading via DuckDB SQL (vectorized)."""
    from src.nlp.cefr_grader import CEFRGrader
    grader = CEFRGrader(subtlex_path=ctx.raw_dir / "SUBTLEX_US.csv")
    rows = db.query("SELECT id, lemma FROM raw_words").fetchall()
    updates = []
    for word_id, lemma in rows:
        level, rank = grader.grade_word(lemma)
        updates.append((rank, level, word_id))
    conn = db.connect()
    conn.executemany(
        "UPDATE raw_words SET frequency_rank = ?, cefr_level = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    logger.info("[Stage 2] CEFR grading applied to %d words.", len(updates))


def _build_lemma_cache(ctx: PipelineContext, db):
    """Build in-memory lemma to id cache for fast lookups."""
    rows = db.query("SELECT id, lemma FROM raw_words").fetchall()
    ctx.lemma_cache = {lemma: word_id for word_id, lemma in rows}
    logger.info("[Stage 2] Lemma cache: %d entries.", len(ctx.lemma_cache))


def _link_word_sentences(ctx: PipelineContext, db):
    """Lemmatize sentences and link to words."""
    from src.nlp.lemmatizer import Lemmatizer
    lemmatizer = Lemmatizer()
    sentences = db.query("SELECT id, text_en FROM raw_sentences").fetchall()
    map_batch = []
    for s_id, text_en in sentences:
        tokens = lemmatizer.lemmatize_text(text_en)
        for token in tokens:
            word_id = ctx.lemma_cache.get(token["lemma"])
            if word_id:
                map_batch.append({"word_id": word_id, "sentence_id": s_id})
        if len(map_batch) >= 10_000:
            db.insert_rows("word_sentence_map", map_batch)
            map_batch = []
    if map_batch:
        db.insert_rows("word_sentence_map", map_batch)
    logger.info("[Stage 2] Word-sentence links: %d", db.row_count("word_sentence_map"))


def _extract_collocations(ctx: PipelineContext, db):
    """Extract collocations from sentences."""
    from src.nlp.chunk_extractor import ChunkExtractor
    extractor = ChunkExtractor()
    sentences = db.query("SELECT text_en FROM raw_sentences").fetchall()
    seen = set()
    colloc_batch = []
    for (text_en,) in sentences:
        chunks = extractor.extract_collocations(text_en)
        for chunk in chunks:
            phrase = chunk["phrase"]
            if phrase not in seen:
                seen.add(phrase)
                colloc_batch.append({
                    "phrase": phrase,
                    "pos_pattern": chunk["pos_pattern"],
                    "cefr_level": "B1",
                    "meaning_vi": None,
                })
    db.insert_rows("collocations", colloc_batch)
    logger.info("[Stage 2] Collocations: %d", db.row_count("collocations"))


def _build_inverse_relations(db):
    """Build inverse hyponym links via SQL set-based operation."""
    db.execute("""
        INSERT OR IGNORE INTO raw_relations (lemma, relation_type, target_text, target_word_id, inverted, source)
        SELECT w.lemma, 'hyponym', rw.lemma, r.lemma, 1, r.source
        FROM raw_relations r
        JOIN raw_words w ON w.lemma = r.lemma
        JOIN raw_words rw ON rw.lemma = r.target_text
        WHERE r.relation_type = 'hypernym' AND r.inverted = 0
    """)
    logger.info("[Stage 2] Inverse relations built.")


def _map_topics(ctx: PipelineContext, db):
    """Map raw topics to curated themes."""
    from src.nlp.topic_mapper import TopicMapper
    topics = db.query("SELECT lemma, raw_topic FROM raw_topics").fetchall()
    mapped = []
    seen = set()
    for lemma, raw_topic in topics:
        theme = TopicMapper.map_topic(raw_topic)
        key = (lemma, theme)
        if key not in seen:
            seen.add(key)
            mapped.append({"lemma": lemma, "topic": theme, "raw_topic": raw_topic})
    db.execute("DELETE FROM raw_topics")
    db.insert_rows("raw_topics", mapped)
    logger.info("[Stage 2] Topics mapped: %d", db.row_count("raw_topics"))

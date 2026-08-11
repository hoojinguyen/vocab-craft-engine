"""Stage 1: Ingest — Download raw data, single-pass Kaikki, corpora."""

import logging
from config.settings import (
    KAIKKI_JSON_PATH, TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH,
    OPENSUBTITLES_EN, OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
    MAX_SENTENCES_PER_CORPUS,
)
from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser
from src.ingestion.downloader import DownloadTask, download_all_parallel
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_1_ingest(ctx: PipelineContext):
    """Download raw data and ingest into DuckDB staging tables."""
    _ensure_raw_data(ctx)
    _ingest_kaikki(ctx)
    _ingest_corpora(ctx)
    logger.info("[Stage 1] Ingest complete.")


def _ensure_raw_data(ctx: PipelineContext):
    """Download missing raw files in parallel."""
    tasks = [
        DownloadTask(
            url="https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
            dest=KAIKKI_JSON_PATH, min_size=1_000_000_000,
            description="Kaikki Dictionary",
        ),
        DownloadTask(
            url="https://downloads.tatoeba.org/exports/sentences.tar.bz2",
            dest=ctx.raw_dir / "sentences.tar.bz2",
            description="Tatoeba Sentences",
        ),
        DownloadTask(
            url="https://downloads.tatoeba.org/exports/links.tar.bz2",
            dest=ctx.raw_dir / "links.tar.bz2",
            description="Tatoeba Links",
        ),
    ]
    download_all_parallel(tasks, max_workers=4)


def _ingest_kaikki(ctx: PipelineContext):
    """Single-pass Kaikki ingestion into DuckDB."""
    if not KAIKKI_JSON_PATH.exists() or KAIKKI_JSON_PATH.stat().st_size == 0:
        logger.warning("[Stage 1] Kaikki dump not found — skipping.")
        return

    db = ctx.duckdb_conn
    db.init_schema()

    parser = KaikkiSinglePassParser(KAIKKI_JSON_PATH)
    total = {cat: 0 for cat in ["word", "phrase", "relation", "topic", "definition"]}

    table_map = {
        "word": "raw_words",
        "phrase": "raw_phrases",
        "relation": "raw_relations",
        "topic": "raw_topics",
        "definition": "raw_definitions",
    }
    for category, batch in parser.parse_stream(batch_size=5000):
        db.insert_rows(table_map[category], batch)
        total[category] += len(batch)
        if total[category] % 50_000 == 0 and category == "word":
            logger.info("   [Kaikki] %d words staged...", total["word"])

    logger.info("[Stage 1] Kaikki: %s", total)


def _ingest_corpora(ctx: PipelineContext):
    """Ingest Tatoeba + parallel corpora into DuckDB."""
    db = ctx.duckdb_conn
    corpora = [
        (OPENSUBTITLES_EN, OPENSUBTITLES_VI, "OpenSubtitles"),
        (ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
        (ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, "Basic-EnVi"),
    ]
    for en_path, vi_path, source in corpora:
        if not en_path.exists() or not vi_path.exists():
            logger.info("   [Corpus] %s missing — skipping.", source)
            continue
        from src.ingestion.opus_parser import ParallelCorpusParser
        from src.ingestion.sentence_filter import SentenceFilter
        sf = SentenceFilter()
        batch = []
        inserted = 0
        for pair in ParallelCorpusParser(en_path, vi_path, source=source).parse_pairs():
            if inserted >= MAX_SENTENCES_PER_CORPUS:
                break
            if not sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
                continue
            batch.append({
                "text_en": pair["text_en"],
                "text_vi": pair["text_vi"],
                "difficulty_score": 2.0,
                "cefr_level": "B1",
                "source": source,
            })
            if len(batch) >= 5000:
                db.insert_rows("raw_sentences", batch)
                inserted += len(batch)
                batch = []
        if batch:
            db.insert_rows("raw_sentences", batch)
            inserted += len(batch)
        logger.info("   [Corpus] %s: %d sentences.", source, inserted)

    logger.info("[Stage 1] Total sentences: %d", db.row_count("raw_sentences"))

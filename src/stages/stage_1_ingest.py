"""Stage 1: Ingest — Download raw data, single-pass Kaikki, corpora."""

import logging

import duckdb

from config.settings import (
    ENVICORPORA_BASIC_EN,
    ENVICORPORA_BASIC_VI,
    ENVICORPORA_TED_LIKE_EN,
    ENVICORPORA_TED_LIKE_VI,
    KAIKKI_JSON_PATH,
    MAX_SENTENCES_PER_CORPUS,
    OPENSUBTITLES_EN,
    OPENSUBTITLES_VI,
)
from src.ingestion.downloader import DownloadTask, download_all_parallel
from src.ingestion.kaikki_sql import (
    drop_landing,
    ingest_kaikki_sql,
    validate_sql_vs_python,
)
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
    """Kaikki ingestion — SQL fast path gated by parity check, Python fallback."""
    if not KAIKKI_JSON_PATH.exists() or KAIKKI_JSON_PATH.stat().st_size == 0:
        logger.warning("[Stage 1] Kaikki dump not found — skipping.")
        return

    db = ctx.duckdb_conn
    db.init_schema()

    gate = _validate_sql_path(db.conn, KAIKKI_JSON_PATH)
    if gate.passed:
        _ingest_kaikki_fast(db.conn, KAIKKI_JSON_PATH)
    else:
        logger.warning(
            "[Stage 1] SQL gate failed (%s) — falling back to Python parser.",
            gate.diffs,
        )
        _ingest_kaikki_fallback(db)


def _validate_sql_path(conn, jsonl_path, sample_lines: int = 50_000):
    """Run the parity gate in-memory; never touches the real staging DB."""
    gate_conn = duckdb.connect(":memory:")
    try:
        return validate_sql_vs_python(gate_conn, jsonl_path, sample_lines=sample_lines)
    finally:
        gate_conn.close()


def _ingest_kaikki_fast(conn, jsonl_path):
    stats = ingest_kaikki_sql(conn, jsonl_path)
    drop_landing(conn)
    logger.info("[Stage 1] Kaikki (SQL fast path): %s", stats)


def _ingest_kaikki_fallback(db):
    from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser

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
    logger.info("[Stage 1] Kaikki (Python fallback): %s", total)


def _ingest_corpora_pair(db, en_path, vi_path, source: str):
    """Ingest parallel EN-VI corpus files directly via DuckDB SQL."""
    conn = db.conn if hasattr(db, "conn") else db

    conn.execute(f"""
        INSERT INTO raw_sentences (text_en, text_vi, difficulty_score, cefr_level, source)
        SELECT
            en.column0 AS text_en,
            vi.column0 AS text_vi,
            2.0 AS difficulty_score,
            'B1' AS cefr_level,
            '{source}' AS source
        FROM read_csv('{en_path}', header=false, auto_detect=false, columns={{'column0': 'VARCHAR'}}, ignore_errors=true) WITH ORDINALITY en
        JOIN read_csv('{vi_path}', header=false, auto_detect=false, columns={{'column0': 'VARCHAR'}}, ignore_errors=true) WITH ORDINALITY vi
          ON en.ordinality = vi.ordinality
        WHERE len(trim(en.column0)) > 2 AND len(trim(vi.column0)) > 2;
    """)


def _ingest_corpora(ctx: PipelineContext):
    """Ingest Tatoeba + parallel corpora into DuckDB via vectorized SQL."""
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
        _ingest_corpora_pair(db, en_path, vi_path, source)
        logger.info("   [Corpus] %s ingested.", source)

    logger.info("[Stage 1] Total sentences: %d", db.row_count("raw_sentences"))

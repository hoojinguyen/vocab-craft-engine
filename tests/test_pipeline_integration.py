"""Integration tests for the full DAG pipeline with small test data."""

import json
import pytest
from pathlib import Path

from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor
from src.pipeline.registry import CheckpointRegistry
from src.db.duckdb_manager import DuckDBManager
from src.db.sqlite_manager import SQLiteBulkWriter


@pytest.fixture
def pipeline_env(tmp_path):
    """Create a minimal pipeline test environment with Kaikki JSONL data."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    # Create small Kaikki JSONL fixture
    kaikki_path = raw_dir / "kaikki.org-dictionary-English.json"
    entries = [
        {"word": "hello", "pos": "intj",
         "sounds": [{"ipa": "/həˈloʊ/", "tags": ["US"]}],
         "senses": [{"glosses": ["a greeting"], "examples": [{"text": "Hello!"}]}],
         "translations": [{"code": "vi", "word": "xin chào"}]},
        {"word": "happy", "pos": "adj",
         "sounds": [{"ipa": "/ˈhæpi/", "tags": ["US", "UK"]}],
         "senses": [{"glosses": ["feeling joy"]}],
         "synonyms": [{"word": "glad"}]},
        {"word": "world", "pos": "noun",
         "sounds": [{"ipa": "/wɜːld/", "tags": ["US"]}],
         "senses": [{"glosses": ["the earth"]}],
         "hypernyms": [{"word": "planet"}]},
        {"word": "kick the bucket", "pos": "idiom",
         "senses": [{"glosses": ["to die"]}]},
    ]
    with open(kaikki_path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    # Create parallel corpus fixture
    en_path = raw_dir / "test_en.txt"
    vi_path = raw_dir / "test_vi.txt"
    en_path.write_text("Hello world.\nI am happy.\n")
    vi_path.write_text("Xin chào thế giới.\nTôi vui.\n")

    # Create SUBTLEX freq file
    subtlex_path = raw_dir / "SUBTLEX_US.csv"
    subtlex_path.write_text("Word,rank\nhello,100\nworld,200\nhappy,300\nplanet,500\n")

    # Create NGSL file
    ngsl_path = raw_dir / "NGSL-1.01.csv"
    ngsl_path.write_text("hello\nworld\nhappy\n")

    ctx = PipelineContext(
        sqlite_path=tmp_path / "test.db",
        duckdb_path=tmp_path / "staging.duckdb",
        processed_dir=tmp_path / "processed",
        output_dir=tmp_path / "output",
        raw_dir=raw_dir,
    )
    ctx.processed_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    return ctx, kaikki_path, en_path, vi_path


def test_full_pipeline_dag(pipeline_env):
    """Full pipeline: ingest → transform → export → SQLite DB with data."""
    ctx, kaikki_path, en_path, vi_path = pipeline_env

    # Use DuckDB staging
    ctx.duckdb_conn = DuckDBManager(ctx.duckdb_path)
    ctx.duckdb_conn.connect()
    ctx.duckdb_conn.init_schema()

    # Stage 1: Ingest Kaikki
    from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser
    parser = KaikkiSinglePassParser(kaikki_path)
    for category, batch in parser.parse_stream(batch_size=100):
        table_map = {
            "word": "raw_words",
            "phrase": "raw_phrases",
            "relation": "raw_relations",
            "topic": "raw_topics",
            "definition": "raw_definitions",
        }
        ctx.duckdb_conn.insert_rows(table_map[category], batch)

    # Verify staging
    assert ctx.duckdb_conn.row_count("raw_words") >= 3
    assert ctx.duckdb_conn.row_count("raw_phrases") >= 1

    # Stage 2: CEFR + lemma cache
    from src.nlp.cefr_grader import CEFRGrader
    grader = CEFRGrader(subtlex_path=ctx.raw_dir / "SUBTLEX_US.csv")
    rows = ctx.duckdb_conn.query("SELECT id, lemma FROM raw_words").fetchall()
    updates = []
    for word_id, lemma in rows:
        level, rank = grader.grade_word(lemma)
        updates.append((rank, level, word_id))
    conn = ctx.duckdb_conn.connect()
    conn.executemany(
        "UPDATE raw_words SET frequency_rank = ?, cefr_level = ? WHERE id = ?",
        updates,
    )
    conn.commit()

    # Verify CEFR applied
    result = ctx.duckdb_conn.query(
        "SELECT cefr_level FROM raw_words WHERE lemma = 'hello'"
    ).fetchone()
    assert result[0] == "A1"

    # Build lemma cache
    ctx.lemma_cache = {
        lemma: wid for wid, lemma in
        ctx.duckdb_conn.query("SELECT id, lemma FROM raw_words").fetchall()
    }

    # Stage 4: Export to SQLite
    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()

    words = ctx.duckdb_conn.query(
        "SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level FROM raw_words"
    ).fetchall()
    writer.insert_words([
        {"lemma": r[1], "pos": r[2], "ipa_uk": r[3], "ipa_us": r[4],
         "frequency_rank": r[5], "cefr_level": r[6]}
        for r in words
    ])

    writer.create_indexes()
    writer.optimize()

    # Verify export
    count = writer.conn.execute("SELECT count(*) FROM words").fetchone()[0]
    assert count >= 3

    hello = writer.conn.execute(
        "SELECT ipa_us, cefr_level FROM words WHERE lemma = 'hello'"
    ).fetchone()
    assert hello[0] == "/həˈloʊ/"
    assert hello[1] == "A1"

    writer.close()
    ctx.duckdb_conn.close()


def test_dag_executor_runs_pipeline_stages(pipeline_env):
    """DAGExecutor runs stages in correct order with checkpoint support."""
    ctx, kaikki_path, en_path, vi_path = pipeline_env

    ctx.duckdb_conn = DuckDBManager(ctx.duckdb_path)
    ctx.duckdb_conn.connect()
    ctx.duckdb_conn.init_schema()

    execution_order = []

    def mock_ingest(context: PipelineContext):
        execution_order.append("ingest")

    def mock_transform(context: PipelineContext):
        execution_order.append("transform")

    def mock_enrich(context: PipelineContext):
        execution_order.append("enrich")

    def mock_export(context: PipelineContext):
        execution_order.append("export")

    registry = CheckpointRegistry(ctx.checkpoint_dir)
    registry.clear_all()

    dag = DAGExecutor(registry=registry)
    dag.add_step("ingest", mock_ingest)
    dag.add_step("transform", mock_transform, depends={"ingest"})
    dag.add_step("enrich", mock_enrich, depends={"transform"})
    dag.add_step("export", mock_export, depends={"enrich"})

    dag.execute(ctx, force_reset=True)

    assert execution_order == ["ingest", "transform", "enrich", "export"]

    # Re-run should skip all (checkpoints exist)
    execution_order2 = []
    dag2 = DAGExecutor(registry=registry)
    dag2.add_step("ingest", lambda c: execution_order2.append("ingest"))
    dag2.add_step("transform", lambda c: execution_order2.append("transform"), depends={"ingest"})
    dag2.add_step("enrich", lambda c: execution_order2.append("enrich"), depends={"transform"})
    dag2.add_step("export", lambda c: execution_order2.append("export"), depends={"enrich"})

    dag2.execute(ctx, force_reset=False)
    assert execution_order2 == []

    # Force reset re-runs all
    dag2.execute(ctx, force_reset=True)
    assert execution_order2 == ["ingest", "transform", "enrich", "export"]


def test_sqlite_wal_mode_after_export(pipeline_env):
    """SQLite DB should be in WAL mode after export."""
    ctx, kaikki_path, en_path, vi_path = pipeline_env

    writer = SQLiteBulkWriter(ctx.sqlite_path)
    writer.connect()
    writer.init_schema()
    writer.insert_words([
        {"lemma": "test", "pos": "noun", "ipa_uk": None, "ipa_us": None,
         "frequency_rank": 1, "cefr_level": "A1"},
    ])
    writer.close()

    import sqlite3
    conn = sqlite3.connect(str(ctx.sqlite_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"

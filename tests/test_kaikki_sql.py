"""Tests for DuckDB-native Kaikki SQL ingestion."""

from pathlib import Path

import duckdb
import pytest

from src.db.duckdb_manager import SCHEMA_SQL
from src.ingestion.kaikki_sql import (
    drop_landing,
    ingest_definitions_sql,
    ingest_kaikki_sql,
    ingest_phrases_sql,
    ingest_relations_sql,
    ingest_topics_sql,
    ingest_vi_translations_sql,
    ingest_words_sql,
    read_kaikki_landing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kaikki_sample.jsonl"


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute(SCHEMA_SQL)
    yield c
    c.close()


def test_read_landing_counts_entries_and_skips_corrupt(conn):
    n = read_kaikki_landing(conn, FIXTURE)
    assert n == 24  # 26 lines total: 1 corrupt skipped + 1 empty-word filtered
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 24


def test_read_landing_is_idempotent(conn):
    read_kaikki_landing(conn, FIXTURE)
    n = read_kaikki_landing(conn, FIXTURE)
    assert n == 24
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 24


def test_classify_definitions_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_definitions_sql(conn)
    rows = conn.execute(
        "SELECT lemma, definition_en, example FROM raw_definitions ORDER BY lemma, definition_en"
    ).fetchall()
    assert ("hello", "a greeting", "Hello world!") in rows
    assert ("happy", "feeling joy", None) in rows
    assert ("run", "to move fast", "Run!") in rows  # raw_glosses fallback
    assert ("run", "to manage", None) in rows
    assert ("take off", "to remove clothing", None) in rows  # multi-word, non-phrase pos
    assert ("carry out", "to perform", None) in rows  # multi-word, non-phrase pos
    assert len(rows) == 6


def test_classify_words_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_words_sql(conn)
    rows = conn.execute(
        "SELECT lemma, pos, ipa_us FROM raw_words ORDER BY lemma"
    ).fetchall()
    assert ("hello", "intj", "/həˈloʊ/") in rows
    assert ("happy", "adj", "/ˈhæpi/") in rows
    assert ("run", "verb", None) in rows  # no sounds on run
    assert ("xyzzy", "noun", None) in rows
    assert ("colour", "noun", "/ˈkʌl.ɚ/") in rows  # untagged fallback for uk, US override
    assert ("fast", "adj", None) in rows
    assert ("big", "adj", None) in rows
    assert ("excited", "adj", None) in rows
    assert ("smile", "noun", None) in rows
    assert ("luck", "noun", None) in rows
    assert ("watch", "verb", None) in rows
    assert len(rows) == 16  # kick the bucket, bite the bullet excluded (phrases)


def test_classify_phrases_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_phrases_sql(conn)
    rows = conn.execute(
        "SELECT phrase, phrase_type, definition_en FROM raw_phrases"
    ).fetchall()
    assert ("kick the bucket", "idiom", "to die") in rows
    assert ("by and large", "phrase", "generally speaking") in rows  # gloss trimmed
    assert ("in a nutshell", "proverb", "briefly") in rows  # first trimmed gloss
    assert ("bite the bullet", "idiom", "to face something") in rows
    assert len(rows) == 4


def test_classify_relations_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_relations_sql(conn)
    rows = conn.execute(
        "SELECT lemma, relation_type, target_text FROM raw_relations ORDER BY lemma, relation_type, target_text"
    ).fetchall()
    assert ("happy", "synonym", "glad") in rows  # top-level
    assert ("happy", "antonym", "sad") in rows  # top-level
    assert ("happy", "hypernym", "emotion") in rows  # top-level
    assert ("run", "synonym", "sprint") in rows  # sense-level
    assert ("carry out", "synonym", "perform") in rows  # multi-word, non-phrase pos
    assert ("bite the bullet", "synonym", "endure") not in rows  # phrase: oracle early-return
    n_fast = conn.execute(
        "SELECT count(*) FROM raw_relations WHERE lemma='fast' AND relation_type='synonym' AND target_text='quick'"
    ).fetchone()[0]
    assert n_fast == 1  # sense-level dup of top-level collapsed; top-level (first) wins
    n_big = conn.execute(
        "SELECT count(*) FROM raw_relations WHERE lemma='big'"
    ).fetchone()[0]
    assert n_big == 25  # cap after dedupe: 27 distinct targets, first 25 in stream order
    assert ("big", "synonym", "ca") not in rows  # 27th target dropped by the cap
    assert len(rows) == 31  # 4 + carry out + fast + big (bite the bullet excluded)


def test_classify_topics_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_topics_sql(conn)
    rows = conn.execute(
        "SELECT lemma, raw_topic FROM raw_topics ORDER BY lemma, raw_topic"
    ).fetchall()
    assert ("happy", "emotion") in rows
    assert ("run", "business") in rows
    assert ("excited", "emotion") in rows  # first occurrence wins, original case kept
    assert ("excited", "EMOTION") not in rows  # case-insensitive dedupe
    assert ("excited", "mood") in rows
    assert ("luck", "chance") in rows  # whitespace-padded topic trimmed
    assert ("smile", "expression") in rows  # empty topic skipped
    assert ("bring up", "communication") in rows  # multi-word, non-phrase pos
    assert all(lemma != "at first" for lemma, _ in rows)  # phrase-classified: oracle early-return
    assert len(rows) == 7


def test_backfill_vi_translations_matches_expected(conn):
    read_kaikki_landing(conn, FIXTURE)
    ingest_words_sql(conn)
    ingest_vi_translations_sql(conn)
    rows = conn.execute(
        "SELECT lemma, vi_translations FROM raw_words ORDER BY lemma"
    ).fetchall()
    assert ("happy", "vui vẻ") in rows
    assert ("run", "chạy") in rows
    assert ("hello", None) in rows
    assert ("xyzzy", None) in rows
    assert ("learn", "học, tìm hiểu") in rows  # dedupe across code AND lang matches, order kept
    assert ("go", "đi") in rows  # lang_code fallback, no code field
    assert ("stay", None) in rows  # "VI" != "vi": exact-case, no match
    assert ("read", "đọc") in rows  # whitespace-stripped word
    assert ("write", "viết") in rows  # non-dict translation skipped
    assert ("watch", None) in rows  # " vi " != "vi": code is NOT trimmed
    n = conn.execute(
        "SELECT count(*) FROM raw_words WHERE vi_translations IS NOT NULL"
    ).fetchone()[0]
    assert n == 6  # happy, run, learn, go, read, write (oracle-verified)


def test_ingest_kaikki_sql_runs_all_steps(conn):
    stats = ingest_kaikki_sql(conn, FIXTURE)
    assert stats["words"] == 16
    assert stats["definitions"] == 6
    assert stats["phrases"] == 4
    assert stats["relations"] == 31
    assert stats["topics"] == 7
    assert stats["vi_translations"] == 6


def test_drop_landing_removes_table(conn):
    read_kaikki_landing(conn, FIXTURE)
    drop_landing(conn)
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'raw_kaikki'"
    ).fetchall()
    assert tables == []


def test_validation_gate_passes_on_fixture(tmp_path):
    from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser
    from src.ingestion.kaikki_sql import validate_sql_vs_python

    parser = KaikkiSinglePassParser(FIXTURE)
    conn = duckdb.connect(str(tmp_path / "gate.duckdb"))
    try:
        result = validate_sql_vs_python(conn, FIXTURE, parser=parser)
    finally:
        conn.close()
    assert result.passed is True
    assert result.diffs == {}


def test_validation_gate_scales_sample(tmp_path):
    from src.ingestion.kaikki_sql import validate_sql_vs_python

    conn = duckdb.connect(str(tmp_path / "gate_slice.duckdb"))
    try:
        result = validate_sql_vs_python(conn, FIXTURE, sample_lines=4)
    finally:
        conn.close()
    assert result.passed is True
    assert result.diffs == {}


def test_validation_gate_fails_when_sql_path_breaks(tmp_path, monkeypatch):
    from src.ingestion import kaikki_sql

    conn = duckdb.connect(str(tmp_path / "gate_broken.duckdb"))
    try:
        monkeypatch.setattr(kaikki_sql, "ingest_phrases_sql", lambda c: 0)
        result = kaikki_sql.validate_sql_vs_python(conn, FIXTURE)
    finally:
        conn.close()
    assert result.passed is False
    assert "phrase" in result.diffs


class _FakeDB:
    """Minimal DuckDBManager stand-in: init_schema + .conn accessor."""

    def __init__(self, conn):
        self.conn = conn

    def init_schema(self):
        pass


def test_stage1_uses_sql_path_when_gate_passes(tmp_path, monkeypatch):
    from src.stages import stage_1_ingest

    called = {"sql": 0, "py": 0}
    conn = duckdb.connect(":memory:")

    def fake_gate(c, path, sample_lines=50_000):
        assert c is conn
        return type("Gate", (), {"passed": True, "diffs": {}})()

    def fake_sql(c, path):
        called["sql"] += 1

    def fake_py(db):
        called["py"] += 1

    monkeypatch.setattr(stage_1_ingest, "KAIKKI_JSON_PATH", FIXTURE)
    monkeypatch.setattr(stage_1_ingest, "_validate_sql_path", fake_gate)
    monkeypatch.setattr(stage_1_ingest, "_ingest_kaikki_fast", fake_sql)
    monkeypatch.setattr(stage_1_ingest, "_ingest_kaikki_fallback", fake_py)

    ctx = stage_1_ingest.PipelineContext(duckdb_conn=_FakeDB(conn))
    stage_1_ingest._ingest_kaikki(ctx)
    conn.close()
    assert called["sql"] == 1
    assert called["py"] == 0


def test_stage1_falls_back_to_python_when_gate_fails(tmp_path, monkeypatch):
    from src.stages import stage_1_ingest

    called = {"sql": 0, "py": 0}
    conn = duckdb.connect(":memory:")

    def fake_gate(c, path, sample_lines=50_000):
        return type("Gate", (), {"passed": False, "diffs": {"word": ["x"]}})()

    def fake_sql(c, path):
        called["sql"] += 1

    def fake_py(db):
        called["py"] += 1

    monkeypatch.setattr(stage_1_ingest, "KAIKKI_JSON_PATH", FIXTURE)
    monkeypatch.setattr(stage_1_ingest, "_validate_sql_path", fake_gate)
    monkeypatch.setattr(stage_1_ingest, "_ingest_kaikki_fast", fake_sql)
    monkeypatch.setattr(stage_1_ingest, "_ingest_kaikki_fallback", fake_py)

    ctx = stage_1_ingest.PipelineContext(duckdb_conn=_FakeDB(conn))
    stage_1_ingest._ingest_kaikki(ctx)
    conn.close()
    assert called["sql"] == 0
    assert called["py"] == 1


def test_stage1_skips_when_dump_missing(tmp_path, monkeypatch):
    from src.stages import stage_1_ingest

    monkeypatch.setattr(stage_1_ingest, "KAIKKI_JSON_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(stage_1_ingest, "_validate_sql_path", lambda *a, **k: 1 / 0)

    ctx = stage_1_ingest.PipelineContext(duckdb_conn=_FakeDB(None))
    stage_1_ingest._ingest_kaikki(ctx)

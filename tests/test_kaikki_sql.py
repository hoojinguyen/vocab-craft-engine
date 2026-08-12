"""Tests for DuckDB-native Kaikki SQL ingestion."""

from pathlib import Path

import duckdb
import pytest

from src.db.duckdb_manager import SCHEMA_SQL
from src.ingestion.kaikki_sql import ingest_words_sql, read_kaikki_landing

FIXTURE = Path(__file__).parent / "fixtures" / "kaikki_sample.jsonl"


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute(SCHEMA_SQL)
    yield c
    c.close()


def test_read_landing_counts_entries_and_skips_corrupt(conn):
    n = read_kaikki_landing(conn, FIXTURE)
    assert n == 5  # 7 lines total: 1 corrupt skipped + 1 empty-word filtered
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 5


def test_read_landing_is_idempotent(conn):
    read_kaikki_landing(conn, FIXTURE)
    n = read_kaikki_landing(conn, FIXTURE)
    assert n == 5
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 5


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
    assert len(rows) == 4  # kick the bucket excluded (phrase)
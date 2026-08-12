"""Tests for DuckDB-native Kaikki SQL ingestion."""

from pathlib import Path

import duckdb
import pytest

from src.ingestion.kaikki_sql import read_kaikki_landing

FIXTURE = Path(__file__).parent / "fixtures" / "kaikki_sample.jsonl"


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    yield c
    c.close()


def test_read_landing_counts_entries_and_skips_corrupt(conn):
    read_kaikki_landing(conn, FIXTURE)
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 5  # 6 lines, 1 corrupt skipped
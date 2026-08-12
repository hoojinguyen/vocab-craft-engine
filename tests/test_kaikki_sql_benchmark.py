"""Benchmark: full Kaikki dump via SQL fast path. Not run by default (marked slow)."""

import time

import duckdb
import pytest

from config.settings import KAIKKI_JSON_PATH
from src.ingestion.kaikki_sql import drop_landing, ingest_kaikki_sql


@pytest.mark.slow
def test_full_kaikki_sql_ingest_under_3_minutes(tmp_path):
    if not KAIKKI_JSON_PATH.exists():
        pytest.skip("Kaikki dump not present")
    conn = duckdb.connect(str(tmp_path / "bench.duckdb"))
    start = time.time()
    stats = ingest_kaikki_sql(conn, KAIKKI_JSON_PATH)
    elapsed = time.time() - start
    drop_landing(conn)
    conn.close()
    print(f"[benchmark] Kaikki SQL ingest: {elapsed:.1f}s, stats={stats}")
    assert elapsed < 180, f"Kaikki SQL ingest took {elapsed:.1f}s — target < 3 min"

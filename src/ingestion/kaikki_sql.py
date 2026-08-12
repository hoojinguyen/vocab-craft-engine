"""DuckDB-native Kaikki ingestion — fast path replacing Python streaming parser.

Mirrors src.ingestion.kaikki_single_pass.KaikkiSinglePassParser semantics
exactly. KaikkiSinglePassParser is kept as the validation oracle and fallback.
"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

LANDING_TABLE = "raw_kaikki"

LANDING_COLUMNS = """{
    'word': 'VARCHAR',
    'pos': 'VARCHAR',
    'sounds': 'JSON',
    'senses': 'JSON',
    'translations': 'JSON',
    'synonyms': 'JSON',
    'antonyms': 'JSON',
    'hypernyms': 'JSON',
    'hyponyms': 'JSON'
}"""

LANDING_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {LANDING_TABLE} (
    word VARCHAR,
    pos VARCHAR,
    sounds JSON,
    senses JSON,
    translations JSON,
    synonyms JSON,
    antonyms JSON,
    hypernyms JSON,
    hyponyms JSON
);
"""


def read_kaikki_landing(conn: duckdb.DuckDBPyConnection, jsonl_path: Path) -> int:
    """Read the Kaikki JSONL into the raw_kaikki landing table via native reader.

    Returns the number of lines read (corrupt lines skipped, not counted).
    """
    conn.execute(LANDING_SCHEMA)
    conn.execute(f"DELETE FROM {LANDING_TABLE}")
    conn.execute(
        f"""
        INSERT INTO {LANDING_TABLE}
        SELECT * FROM read_json(
            '{jsonl_path}',
            format='newline_delimited',
            ignore_errors=true,
            columns={LANDING_COLUMNS}
        )
        WHERE NULLIF(TRIM(word), '') IS NOT NULL
        """
    )
    n = conn.execute(f"SELECT count(*) FROM {LANDING_TABLE}").fetchone()[0]
    logger.info("Landing read: %d entries (corrupt lines skipped)", n)
    return n

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


def _sound_scan(alias: str) -> str:
    """UNNEST fragment over a landing row's sounds, with 1-based ordinality."""
    return f"UNNEST(CAST(t.sounds AS JSON[])) WITH ORDINALITY AS {alias}(elt, pos)"


def _tagged(alias: str, tag: str) -> str:
    return (
        f"list_contains(COALESCE(CAST({alias}.elt->'tags' AS VARCHAR[]), []::VARCHAR[]), '{tag}')"
    )


def _has_ipa(alias: str) -> str:
    return f"COALESCE(TRIM({alias}.elt->>'ipa'), '') != ''"


def _untagged(alias: str) -> str:
    return (
        f"NOT ({_tagged(alias, 'UK')} OR {_tagged(alias, 'British')} "
        f"OR {_tagged(alias, 'US')} OR {_tagged(alias, 'American')})"
    )


def ingest_words_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Classify single-word entries from landing into raw_words.

    Mirrors KaikkiSinglePassParser._extract_word/_extract_ipas exactly:
    - word with no space -> word (stripped, lowercased)
    - ipa_uk: last UK/British-tagged sound, else the first untagged sound
      appearing before any UK-tagged sound, else NULL
    - ipa_us: last US/American-tagged sound, else the same untagged
      fallback, else NULL
    """
    first_uk_pos = (
        f"(SELECT min(p.pos) FROM {_sound_scan('p')} "
        f"WHERE {_has_ipa('p')} AND ({_tagged('p', 'UK')} OR {_tagged('p', 'British')}))"
    )
    first_untagged_pos = (
        f"(SELECT min(u.pos) FROM {_sound_scan('u')} "
        f"WHERE {_has_ipa('u')} AND {_untagged('u')} "
        f"AND u.pos < COALESCE({first_uk_pos}, 1000000))"
    )

    def ipa_subquery(alias: str, tag_match: str) -> str:
        return (
            f"(SELECT {alias}.elt->>'ipa' FROM {_sound_scan(alias)} "
            f"WHERE {_has_ipa(alias)} AND ({tag_match} OR {alias}.pos = COALESCE({first_untagged_pos}, -1)) "
            f"ORDER BY {alias}.pos DESC LIMIT 1)"
        )

    ipa_uk = ipa_subquery("e", f"{_tagged('e', 'UK')} OR {_tagged('e', 'British')}")
    ipa_us = ipa_subquery("f", f"{_tagged('f', 'US')} OR {_tagged('f', 'American')}")

    conn.execute(
        f"""
        INSERT OR IGNORE INTO raw_words (lemma, pos, ipa_uk, ipa_us)
        SELECT
            TRIM(LOWER(t.word)),
            LOWER(COALESCE(t.pos, '')),
            {ipa_uk},
            {ipa_us}
        FROM {LANDING_TABLE} t
        WHERE position(' ' in t.word) = 0
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_words").fetchone()[0]
    logger.info("Words classified: %d", n)
    return n


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

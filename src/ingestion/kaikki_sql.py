"""DuckDB-native Kaikki ingestion — fast path replacing Python streaming parser.

Mirrors src.ingestion.kaikki_single_pass.KaikkiSinglePassParser semantics
exactly. KaikkiSinglePassParser is kept as the validation oracle and fallback.
"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

LANDING_TABLE = "raw_kaikki"

PHRASE_POS_ALLOWED = ("idiom", "phrasal verb", "proverb", "phrase")
MAX_WORDS_PER_PHRASE = 6
CLEAN_CHARS_PATTERN = "^[a-zA-Z '.-]+$"

_PHRASE_POS_LIST = "(" + ", ".join(f"'{p}'" for p in PHRASE_POS_ALLOWED) + ")"

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


def ingest_definitions_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Classify senses into raw_definitions.

    Mirrors KaikkiSinglePassParser._extract_definitions exactly:
    - UNNEST senses per entry; only phrase-classified entries are excluded
      (is_phrase: space in word AND pos in phrase-allowed set) — multi-word
      non-phrase entries keep their full lemma, matching the oracle
    - glosses preferred, raw_glosses fallback when glosses empty
    - one row per gloss (trimmed), empty glosses kept (oracle emits them)
    - example: first non-empty sense example — dict .text or bare string
    - source: Kaikki/Wiktionary
    - lemma: word stripped + lowercased
    """
    conn.execute(
        f"""
        INSERT INTO raw_definitions (lemma, definition_en, example, source)
        SELECT
            TRIM(LOWER(t.word)) AS lemma,
            glosses.definition_en,
            sense.example,
            'Kaikki/Wiktionary' AS source
        FROM {LANDING_TABLE} t
        CROSS JOIN LATERAL (
            SELECT
                elt,
                list_extract(
                    list_filter(
                        [CASE WHEN json_type(e) = 'OBJECT' THEN e->>'text'
                              WHEN json_type(e) = 'VARCHAR' THEN e->>'$'
                              ELSE NULL END
                         FOR e IN CAST(elt->'examples' AS JSON[])],
                        x -> x IS NOT NULL AND x != ''),
                    1) AS example
            FROM UNNEST(CAST(t.senses AS JSON[])) AS s(elt)
        ) sense
        CROSS JOIN LATERAL (
            SELECT TRIM(gl) AS definition_en
            FROM UNNEST(
                CASE WHEN len(CAST(sense.elt->'glosses' AS VARCHAR[])) > 0
                     THEN CAST(sense.elt->'glosses' AS VARCHAR[])
                     ELSE CAST(sense.elt->'raw_glosses' AS VARCHAR[]) END) AS g(gl)
        ) glosses
        WHERE NOT (
            position(' ' in TRIM(t.word)) > 0
            AND LOWER(TRIM(COALESCE(t.pos, ''))) IN
                ('idiom', 'phrasal verb', 'proverb', 'phrase')
        )
          AND glosses.definition_en IS NOT NULL
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_definitions").fetchone()[0]
    logger.info("Definitions classified: %d", n)
    return n


def ingest_phrases_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Classify multiword entries into raw_phrases.

    Mirrors KaikkiSinglePassParser._extract_phrase exactly:
    - is_phrase: space in word AND pos in allowed set (pos lowercased+trimmed)
    - word: TRIM(LOWER(word)); must contain space
    - <=6 words unless pos = proverb (whitespace-run split, like str.split)
    - regex ^[a-zA-Z '.-]+$ on the cleaned (trimmed) word
    - definition_en: first non-empty trimmed gloss, first sense that has one
      (glosses preferred, raw_glosses fallback); skip if none
    - ipa: first sound with truthy ipa (no tag filtering, no trim)
    - phrase_type = pos.replace(' ', '_')
    - INSERT OR IGNORE: phrase is UNIQUE; the dump can repeat a phrase
      (e.g. "et al." twice), same as ingest_words_sql dedupes by lemma
    """
    conn.execute(
        f"""
        INSERT OR IGNORE INTO raw_phrases (phrase, phrase_type, pos, definition_en, ipa)
        SELECT
            TRIM(LOWER(t.word)) AS phrase,
            replace(LOWER(TRIM(COALESCE(t.pos, ''))), ' ', '_') AS phrase_type,
            LOWER(TRIM(COALESCE(t.pos, ''))) AS pos,
            glosses.definition_en,
            (SELECT list_extract(
                list_filter(
                    [COALESCE(e->>'ipa', '')
                     FOR e IN CAST(t.sounds AS JSON[])],
                    x -> x != ''),
                1)) AS ipa
        FROM {LANDING_TABLE} t
        CROSS JOIN LATERAL (
            SELECT definition_en
            FROM (
                SELECT
                    list_extract(
                        list_filter(
                            [COALESCE(CAST(gl AS VARCHAR), '')
                             FOR gl IN CAST(
                                 CASE WHEN len(CAST(s.elt->'glosses' AS VARCHAR[])) > 0
                                      THEN CAST(s.elt->'glosses' AS VARCHAR[])
                                      ELSE CAST(s.elt->'raw_glosses' AS VARCHAR[]) END
                             AS VARCHAR[])],
                            x -> TRIM(x) != ''),
                        1) AS definition_en
                FROM UNNEST(CAST(t.senses AS JSON[])) AS s(elt)
            ) per_sense
            WHERE per_sense.definition_en IS NOT NULL
            LIMIT 1
        ) glosses
        WHERE position(' ' in TRIM(t.word)) > 0
          AND LOWER(TRIM(COALESCE(t.pos, ''))) IN {_PHRASE_POS_LIST}
          AND (len(string_split_regex(TRIM(t.word), '\\s+')) <= {MAX_WORDS_PER_PHRASE}
               OR LOWER(TRIM(COALESCE(t.pos, ''))) = 'proverb')
          AND regexp_matches(TRIM(t.word), '{CLEAN_CHARS_PATTERN.replace("'", "''")}')
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_phrases").fetchone()[0]
    logger.info("Phrases classified: %d", n)
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

"""DuckDB-native Kaikki ingestion — fast path replacing Python streaming parser.

Mirrors src.ingestion.kaikki_single_pass.KaikkiSinglePassParser semantics
exactly. KaikkiSinglePassParser is kept as the validation oracle and fallback.
"""

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from src.db.duckdb_manager import SCHEMA_SQL
from src.ingestion.kaikki_single_pass import (
    CLEAN_CHARS_PATTERN,
    MAX_RELATIONS_PER_TYPE,
    MAX_WORDS_PER_PHRASE,
    PHRASE_POS_ALLOWED,
    KaikkiSinglePassParser,
)

logger = logging.getLogger(__name__)

LANDING_TABLE = "raw_kaikki"

_PHRASE_POS_LIST = "(" + ", ".join("'" + p + "'" for p in PHRASE_POS_ALLOWED) + ")"

# Python str.strip() removes ASCII whitespace [ \t\n\r\v\f]; DuckDB TRIM
# defaults to spaces only. E-string escapes cover \t\n\r\f but not \v, hence
# chr(11) for the vertical tab. Unicode whitespace (e.g. \xa0) is not
# stripped — known parity limit, JSON dict data never contains those.
_PY_STRIP_SET = "E' \\t\\n\\r\\f' || chr(11)"

RELATION_SECTIONS = ("synonyms", "antonyms", "hypernyms", "hyponyms")
RELATION_TYPES = {
    "synonyms": "synonym",
    "antonyms": "antonym",
    "hypernyms": "hypernym",
    "hyponyms": "hyponym",
}

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


def _exclude_phrase(table_alias: str) -> str:
    """SQL fragment excluding phrase-classified entries (space in word AND pos
    in the phrase-allowed set) — the oracle early-returns for phrases."""
    return (
        f"NOT (position(' ' in TRIM({table_alias}.word)) > 0 "
        f"AND LOWER(TRIM(COALESCE({table_alias}.pos, ''))) IN {_PHRASE_POS_LIST})"
    )


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
        WHERE {_exclude_phrase('t')}
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
      (e.g. "et al." twice), same as ingest_words_sql dedupes by lemma.
      INSERT OR IGNORE collapses duplicate phrases (UNIQUE(phrase)); when the
      same phrase appears under multiple POS, the surviving row is
      input-order-dependent — use set-semantics when comparing against the
      oracle.
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
                            [TRIM(COALESCE(CAST(gl AS VARCHAR), ''))
                             FOR gl IN CAST(
                                 CASE WHEN len(CAST(s.elt->'glosses' AS VARCHAR[])) > 0
                                      THEN CAST(s.elt->'glosses' AS VARCHAR[])
                                      ELSE CAST(s.elt->'raw_glosses' AS VARCHAR[]) END
                             AS VARCHAR[])],
                            x -> x != ''),
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
          AND regexp_matches(TRIM(t.word), '{CLEAN_CHARS_PATTERN.pattern.replace("'", "''")}')
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_phrases").fetchone()[0]
    logger.info("Phrases classified: %d", n)
    return n


def _json_array_cast(expr: str) -> str:
    """CAST a JSON value to JSON[] without raising on non-arrays.

    DuckDB's CAST(x AS JSON[]) raises ConversionException when x is a JSON
    object/string/number; one malformed-but-parseable line would abort the
    whole ingest. Non-array (and NULL) values map to an empty array, which
    yields zero rows — matching the oracle, whose list(...) of a dict
    iterates keys (non-dicts are skipped) and whose `or []` covers NULL.
    """
    return (
        f"CAST(CASE WHEN json_type({expr}) = 'ARRAY' "
        f"THEN {expr} ELSE '[]'::JSON END AS JSON[])"
    )


def _relations_branch(section: str, relation_type: str, sense_level: bool) -> str:
    """One UNION ALL branch of the relations stream (top-level or sense-level).

    Targets are normalized to LOWER(TRIM(elt->>'word', _PY_STRIP_SET)) — the
    full Python strip() ASCII whitespace set, matching the oracle — before
    every filter, and non-object candidates yield NULL targets (duckdb's
    '->>'word'' on a JSON non-object is NULL), matching the oracle's
    isinstance skip.

    ordinal reproduces the oracle's stream order: top-level elements in array
    order (rel.pos), then each sense's array in sense order
    (s.pos * 1000000 + rel.pos), so any smaller ordinal is always earlier.
    """
    if sense_level:
        array_expr = f"s.elt->'{section}'"
        from_clause = (
            f"FROM {LANDING_TABLE} t\n"
            f"CROSS JOIN LATERAL UNNEST(CAST(t.senses AS JSON[])) WITH ORDINALITY AS s(elt, pos)\n"
            f"CROSS JOIN LATERAL UNNEST({_json_array_cast(array_expr)}) "
            f"WITH ORDINALITY AS rel(elt, pos)"
        )
        ordinal = "s.pos * 1000000 + rel.pos"
    else:
        array_expr = f"t.{section}"
        from_clause = (
            f"FROM {LANDING_TABLE} t\n"
            f"CROSS JOIN LATERAL UNNEST({_json_array_cast(array_expr)}) "
            f"WITH ORDINALITY AS rel(elt, pos)"
        )
        ordinal = "rel.pos"

    return f"""
    SELECT
        TRIM(LOWER(t.word)) AS lemma,
        '{relation_type}' AS relation_type,
        LOWER(TRIM(rel.elt->>'word', {_PY_STRIP_SET})) AS target_text,
        '{section}' AS source,
        {ordinal} AS ordinal
    {from_clause}
    WHERE {_exclude_phrase('t')}
      AND target_text IS NOT NULL
      AND target_text != ''
      AND target_text != lemma
      AND len(target_text) > 1
      AND regexp_matches(target_text, '{CLEAN_CHARS_PATTERN.pattern.replace("'", "''")}')
    """


def ingest_relations_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Classify relations from top-level + sense-level arrays into raw_relations.

    Mirrors KaikkiSinglePassParser._extract_relations exactly:
    - fixed section order synonyms -> synonym, antonyms -> antonym,
      hypernyms -> hypernym, hyponyms -> hyponym; per section, top-level
      array elements first, then each sense's array in sense order
    - non-object candidates skipped (non-object JSON yields NULL ->>'word'')
    - target = word stripped + lowercased; skip empty, self (== lemma),
      length-1, or targets failing ^[a-zA-Z '.-]+$
    - dedupe on (relation_type, target_text) per lemma — first occurrence in
      stream order wins (DISTINCT ON before the cap, like the oracle's
      seen-set before its count); raw_relations has no unique constraint so
      dedupe must happen in SQL
    - cap 25 per (section, lemma) applied AFTER dedupe (row_number over
      ordinal), keeping the first MAX_RELATIONS_PER_TYPE in stream order
    - phrase-classified entries excluded (space in word AND pos in the
      phrase-allowed set), same predicate as ingest_definitions_sql — the
      oracle returns early for phrases in _classify
    - source is the section name for both top-level and sense rows
    """
    branches = []
    for section in RELATION_SECTIONS:
        relation_type = RELATION_TYPES[section]
        branches.append(_relations_branch(section, relation_type, sense_level=False))
        branches.append(_relations_branch(section, relation_type, sense_level=True))
    conn.execute(
        f"""
        INSERT INTO raw_relations (lemma, relation_type, target_text, source)
        SELECT lemma, relation_type, target_text, source
        FROM (
            SELECT
                lemma,
                relation_type,
                target_text,
                source,
                row_number() OVER (
                    PARTITION BY lemma, relation_type ORDER BY ordinal
                ) AS rn
            FROM (
                SELECT DISTINCT ON (lemma, relation_type, target_text)
                    lemma, relation_type, target_text, source, ordinal
                FROM (
                    {"UNION ALL".join(branches)}
                ) branches
                ORDER BY lemma, relation_type, target_text, ordinal
            ) deduped
        ) ranked
        WHERE rn <= {MAX_RELATIONS_PER_TYPE}
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_relations").fetchone()[0]
    logger.info("Relations classified: %d", n)
    return n


def ingest_vi_translations_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Backfill vi_translations on raw_words from landing translations.

    Mirrors KaikkiSinglePassParser._extract_vi_translations exactly:
    - translations where code = 'vi' OR lang = 'Vietnamese' — EXACT,
      case-sensitive equality; code falls back to lang_code when falsy
      (COALESCE(NULLIF(code, ''), lang_code)), like the oracle's
      `trans.get('code') or trans.get('lang_code')` — code is NOT
      trimmed (whitespace-padded codes are truthy and never match, e.g.
      ' vi '); neither code nor lang is lowercased, so 'VI' never
      matches
    - translation word = elt->>'word' stripped with the Python whitespace
      set; empty-after-strip skipped (mirrors .strip() then falsy check)
    - dedupe on the stripped word EXACT (case-sensitive) per lemma — first
      occurrence in stream order wins via the module's DISTINCT ON pattern
      (the oracle's seen-list keeps first occurrence), then survivors are
      joined with ', ' in per-entry stream order (string_agg over ordinal;
      ordinal restarts per entry, so cross-entry order for multi-entry
      lemmas is unstable — inside the documented parity limit below)
    - non-dict translation elements yield NULL code/lang (->> on a JSON
      string/number is NULL), filtered out — mirrors the isinstance skip;
      _json_array_cast() guards non-array translations (0 rows, no raise)
    - entries with no matching translations are not touched: the
      UPDATE ... FROM only assigns rows the subquery produced, so existing
      NULLs are kept
    - lemma = word stripped + lowercased, joined against raw_words.lemma
      (the same normalization as ingest_words_sql), which also limits
      backfill to single-word entries — the oracle only computes
      vi_translations for words (phrases get definition_vi instead)

    Parity limit: the oracle computes the string per landing entry and
    INSERT OR IGNORE keeps the first entry's string when the same lemma
    appears in MULTIPLE landing entries (the dump has multi-POS repeats);
    this SQL aggregates translations across all landing entries for a
    lemma. vi_translations is enrichment and not gate-pinned (the Task 9
    gate compares word rows on (lemma, pos, ipa_uk, ipa_us)), so this
    divergence is accepted and documented.
    """
    code_expr = "COALESCE(NULLIF(elt->>'code', ''), elt->>'lang_code')"
    conn.execute(
        f"""
        UPDATE raw_words
        SET vi_translations = sub.vi
        FROM (
            SELECT lemma, string_agg(w, ', ' ORDER BY ordinal) AS vi
            FROM (
                SELECT DISTINCT ON (lemma, w)
                    lemma, w, ordinal
                FROM (
                    SELECT
                        TRIM(LOWER(t.word)) AS lemma,
                        TRIM(elt->>'word', {_PY_STRIP_SET}) AS w,
                        trans.pos AS ordinal
                    FROM {LANDING_TABLE} t
                    CROSS JOIN LATERAL UNNEST({_json_array_cast('t.translations')})
                        WITH ORDINALITY AS trans(elt, pos)
                    WHERE ({code_expr} = 'vi' OR (elt->>'lang') = 'Vietnamese')
                      AND w IS NOT NULL
                      AND w != ''
                ) stream
                ORDER BY lemma, w, ordinal
            ) deduped
            GROUP BY lemma
        ) sub
        WHERE raw_words.lemma = sub.lemma
        """
    )
    n = conn.execute(
        "SELECT count(*) FROM raw_words WHERE vi_translations IS NOT NULL"
    ).fetchone()[0]
    logger.info("VI translations backfilled: %d", n)
    return n


def ingest_topics_sql(conn: duckdb.DuckDBPyConnection) -> int:
    """Classify sense-level topics into raw_topics.

    Mirrors KaikkiSinglePassParser._extract_topics exactly:
    - non-phrase entries only (space in word AND pos in the phrase-allowed
      set excluded, via _exclude_phrase) — the oracle returns early for
      phrases in _classify
    - senses unnested in array order, each sense's topics in array order;
      topic = (raw or '').strip(), empty/whitespace-only skipped
    - dedupe on lower(raw_topic) per lemma — first occurrence in stream
      order wins, keeping the original (stripped) case, like the oracle's
      seen-set; raw_topics has no unique constraint so dedupe must be in SQL
    - lemma = word stripped + lowercased
    - ordinal = s.pos * 1000000 + topic.pos reproduces the oracle's stream
      order: senses in array order, topics within each sense in array order —
      the same encoding scheme as _relations_branch, so any earlier stream
      position has a smaller ordinal and DISTINCT ON picks the true first
      occurrence
    - non-string topic elements are coerced to text via ->>'$' (e.g. a JSON
      number becomes '5'), where the oracle would raise on (raw or '').strip()
      of a non-string — SQL is deliberately more tolerant
    - whitespace trim parity limit: TRIM with _PY_STRIP_SET covers the
      ASCII [ \\t\\n\\r\\v\\f] set that Python str.strip() removes; Python
      additionally strips Unicode whitespace (e.g. \\xa0), which JSON dict
      data never contains — accepted divergence
    - _json_array_cast() guards both senses and topics so a malformed-but-
      parseable line can't abort the ingest (non-array -> zero rows,
      matching the oracle's tolerance)
    """
    conn.execute(
        f"""
        INSERT INTO raw_topics (lemma, raw_topic)
        SELECT lemma, raw_topic
        FROM (
            SELECT DISTINCT ON (lemma, lower(raw_topic))
                lemma, raw_topic
            FROM (
                SELECT
                    TRIM(LOWER(t.word)) AS lemma,
                    TRIM(topic.elt->>'$', {_PY_STRIP_SET}) AS raw_topic,
                    s.pos * 1000000 + topic.pos AS ordinal
                FROM {LANDING_TABLE} t
                CROSS JOIN LATERAL UNNEST({_json_array_cast('t.senses')})
                    WITH ORDINALITY AS s(elt, pos)
                CROSS JOIN LATERAL UNNEST({_json_array_cast("s.elt->'topics'")})
                    WITH ORDINALITY AS topic(elt, pos)
                WHERE {_exclude_phrase('t')}
                  AND raw_topic IS NOT NULL
                  AND raw_topic != ''
            ) stream
            ORDER BY lemma, lower(raw_topic), ordinal
        ) deduped
        """
    )
    n = conn.execute("SELECT count(*) FROM raw_topics").fetchone()[0]
    logger.info("Topics classified: %d", n)
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


def ingest_kaikki_sql(
    conn: duckdb.DuckDBPyConnection, jsonl_path: Path
) -> dict[str, int]:
    """Run the full SQL fast path: landing read + all classifications.

    Returns per-table row counts for reporting.
    """
    read_kaikki_landing(conn, jsonl_path)
    stats = {
        "words": ingest_words_sql(conn),
        "definitions": ingest_definitions_sql(conn),
        "phrases": ingest_phrases_sql(conn),
        "relations": ingest_relations_sql(conn),
        "topics": ingest_topics_sql(conn),
    }
    stats["vi_translations"] = ingest_vi_translations_sql(conn)
    logger.info("Ingest fast path complete: %s", stats)
    return stats


def drop_landing(conn: duckdb.DuckDBPyConnection):
    """Drop the raw_kaikki landing table to keep staging lean."""
    conn.execute(f"DROP TABLE IF EXISTS {LANDING_TABLE}")
    logger.info("Landing table dropped.")


@dataclass
class ValidationResult:
    """Outcome of a SQL-fast-path vs Python-parser parity check."""

    passed: bool
    diffs: dict[str, list[str]] = field(default_factory=dict)


def _rows_from_parser(
    parser: KaikkiSinglePassParser, n_lines: int
) -> dict[str, set[tuple]]:
    """Parse the first n_lines of the dump with the Python parser.

    Physical lines are counted (blank/corrupt included), matching
    parse_all(max_entries) slice semantics. Per-table row sets use the same
    column shapes as _rows_from_sql so the gate can diff them directly.

    The oracle's own _stream_jsonl/_classify_to_dict drive this loop, so the
    gate validates against the LIVE oracle dispatch instead of a private
    copy that could drift.
    """
    rows: dict[str, set[tuple]] = {
        k: set() for k in ["word", "definition", "phrase", "relation", "topic"]
    }
    batch: dict[str, list[dict]] = {
        "word": [], "phrase": [], "relation": [], "topic": [], "definition": []
    }
    for i, item in parser._stream_jsonl():
        if i >= n_lines:
            break
        parser._classify_to_dict(item, batch)
        for category, parsed in batch.items():
            for r in parsed:
                if category == "word":
                    rows["word"].add((r["lemma"], r["pos"], r.get("ipa_uk"), r.get("ipa_us")))
                elif category == "phrase":
                    rows["phrase"].add(
                        (r["phrase"], r["phrase_type"], r.get("definition_en"), r.get("ipa"))
                    )
                elif category == "definition":
                    rows["definition"].add((r["lemma"], r["definition_en"], r.get("example")))
                elif category == "relation":
                    rows["relation"].add((r["lemma"], r["relation_type"], r["target_text"]))
                elif category == "topic":
                    rows["topic"].add((r["lemma"], r["raw_topic"]))
        batch = {k: [] for k in batch}
    return rows


def _rows_from_sql(
    conn: duckdb.DuckDBPyConnection, n_lines: int, jsonl_path: Path
) -> dict[str, set[tuple]]:
    """Run the SQL fast path on the first n_lines, return per-table row sets.

    The slice is materialized to a tempfile so read_json sees exactly the
    same physical lines (corrupt ones skipped by ignore_errors) the parser
    iterates. The 5 raw_* tables are wiped first — the gate is safe to run
    on a conn that already holds staged data from a prior read.
    """
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            sample_path = Path(f.name)
            with open(jsonl_path, "r", encoding="utf-8") as src:
                for i, line in enumerate(src):
                    if i >= n_lines:
                        break
                    f.write(line)
        conn.execute(SCHEMA_SQL)
        read_kaikki_landing(conn, sample_path)
        conn.execute("DELETE FROM raw_words")
        conn.execute("DELETE FROM raw_definitions")
        conn.execute("DELETE FROM raw_phrases")
        conn.execute("DELETE FROM raw_relations")
        conn.execute("DELETE FROM raw_topics")
        ingest_words_sql(conn)
        ingest_definitions_sql(conn)
        ingest_phrases_sql(conn)
        ingest_relations_sql(conn)
        ingest_topics_sql(conn)
        ingest_vi_translations_sql(conn)

        return {
            "word": set(
                conn.execute(
                    "SELECT lemma, pos, ipa_uk, ipa_us FROM raw_words"
                ).fetchall()
            ),
            "definition": set(
                conn.execute(
                    "SELECT lemma, definition_en, example FROM raw_definitions"
                ).fetchall()
            ),
            "phrase": set(
                conn.execute(
                    "SELECT phrase, phrase_type, definition_en, ipa FROM raw_phrases"
                ).fetchall()
            ),
            "relation": set(
                conn.execute(
                    "SELECT lemma, relation_type, target_text FROM raw_relations"
                ).fetchall()
            ),
            "topic": set(
                conn.execute("SELECT lemma, raw_topic FROM raw_topics").fetchall()
            ),
        }
    finally:
        sample_path.unlink(missing_ok=True)


def validate_sql_vs_python(
    conn: duckdb.DuckDBPyConnection,
    jsonl_path: Path,
    sample_lines: int = 50_000,
    parser: KaikkiSinglePassParser | None = None,
) -> ValidationResult:
    """Compare the SQL fast path against the Python parser on a sample.

    Both sides run on the first `sample_lines` physical lines of the dump
    (blank and corrupt lines count toward the slice, matching
    parse_all(max_entries) semantics). Callers MUST pass a scratch conn:
    the raw_* tables on it are wiped first, so the gate cannot be pointed
    at the real staging DB. If any ingest step raises, the exception
    propagates (Task 10's try/except turns that into a fallback).

    Gate scope — columns compared per table:
    - word:       (lemma, pos, ipa_uk, ipa_us) — vi_translations deliberately
      excluded: multi-entry lemmas aggregate translations differently in the
      SQL backfill (documented divergence in ingest_vi_translations_sql)
    - definition: (lemma, definition_en, example)
    - phrase:     (phrase, phrase_type, definition_en, ipa)
    - relation:   (lemma, relation_type, target_text)
    - topic:      (lemma, raw_topic)

    Sets, not multisets: raw_phrases.phrase is UNIQUE, so the SQL path
    collapses repeated dump entries where the oracle keeps duplicates; the
    SQL relations/topics paths dedupe via DISTINCT ON, mirroring the
    oracle's seen-sets — set comparison is the right shape for both.
    """
    parser = parser or KaikkiSinglePassParser(jsonl_path)
    py_rows = _rows_from_parser(parser, sample_lines)
    sql_rows = _rows_from_sql(conn, sample_lines, jsonl_path)

    diffs: dict[str, list[str]] = {}
    for table in py_rows:
        only_py = py_rows[table] - sql_rows[table]
        only_sql = sql_rows[table] - py_rows[table]
        if only_py or only_sql:
            diffs[table] = [
                f"only_py[{len(only_py)}]: {sorted(only_py, key=str)[:3]}",
                f"only_sql[{len(only_sql)}]: {sorted(only_sql, key=str)[:3]}",
            ]
    passed = not diffs
    if passed:
        logger.info("Validation gate PASSED (sample=%d lines).", sample_lines)
    else:
        logger.warning("Validation gate FAILED: %s", diffs)
    return ValidationResult(passed=passed, diffs=diffs)

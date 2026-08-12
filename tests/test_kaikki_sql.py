"""Tests for DuckDB-native Kaikki SQL ingestion."""

from pathlib import Path

import duckdb
import pytest

from src.db.duckdb_manager import SCHEMA_SQL
from src.ingestion.kaikki_sql import (
    ingest_definitions_sql,
    ingest_phrases_sql,
    ingest_relations_sql,
    ingest_topics_sql,
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
    assert n == 18  # 20 lines total: 1 corrupt skipped + 1 empty-word filtered
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 18


def test_read_landing_is_idempotent(conn):
    read_kaikki_landing(conn, FIXTURE)
    n = read_kaikki_landing(conn, FIXTURE)
    assert n == 18
    n = conn.execute("SELECT count(*) FROM raw_kaikki").fetchone()[0]
    assert n == 18


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
    assert len(rows) == 10  # kick the bucket, bite the bullet excluded (phrases)


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
    assert ("excited", "EMOTION") in rows  # first occurrence wins, original case kept
    assert ("excited", "emotion") not in rows  # case-insensitive dedupe
    assert ("excited", "mood") in rows
    assert ("luck", "chance") in rows  # whitespace-padded topic trimmed
    assert ("smile", "expression") in rows  # empty topic skipped
    assert ("bring up", "communication") in rows  # multi-word, non-phrase pos
    assert all(lemma != "at first" for lemma, _ in rows)  # phrase-classified: oracle early-return
    assert len(rows) == 7

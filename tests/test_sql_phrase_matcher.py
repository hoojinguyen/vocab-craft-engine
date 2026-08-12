"""
Unit tests for match_phrases_sql in PhraseExampleMatcher.
"""

import sqlite3
import pytest
from src.nlp.phrase_example_matcher import PhraseExampleMatcher


def test_sql_phrase_matching(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    cursor.execute("INSERT INTO sentences VALUES (1, 'Never give up your dreams.', 'A1');")
    cursor.execute("INSERT INTO sentences VALUES (2, 'He gave up smoking last year.', 'A2');")
    cursor.execute("INSERT INTO sentences VALUES (3, 'An unrelated sentence here.', 'B1');")
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 10, "phrase": "give up"}])

    sentence_ids = [r["sentence_id"] for r in results]
    assert 1 in sentence_ids
    assert 2 in sentence_ids
    assert 3 not in sentence_ids
    conn.close()


def test_sql_phrase_matching_cefr_ranking(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    cursor.execute("INSERT INTO sentences VALUES (1, 'Break a leg at the show tonight!', 'B1');")
    cursor.execute("INSERT INTO sentences VALUES (2, 'She told me to break a leg before the exam.', 'A1');")
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 10, "phrase": "break a leg"}])

    # A1 (id 2) should rank before B1 (id 1)
    assert [r["sentence_id"] for r in results] == [2, 1]
    assert [r["rank"] for r in results] == [1, 2]
    conn.close()


def test_sql_phrase_matching_boundary_check(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    cursor.execute("INSERT INTO sentences VALUES (1, 'I finally decided to give up smoking.', 'A2');")
    cursor.execute("INSERT INTO sentences VALUES (2, 'Please do not give upward pressure to the door.', 'C1');")
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 20, "phrase": "give up"}])

    sentence_ids = [r["sentence_id"] for r in results]
    assert 1 in sentence_ids
    assert 2 not in sentence_ids
    conn.close()


def test_sql_phrase_matching_caps_at_five(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    for i in range(1, 10):
        cursor.execute("INSERT INTO sentences VALUES (?, ?, 'A1');", (i, f"sample phrase number {i} here"))
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 40, "phrase": "sample phrase"}])

    assert len(results) == 5
    conn.close()


def test_sql_phrase_matching_empty_phrase(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    cursor.execute("INSERT INTO sentences VALUES (1, 'Some sentence.', 'A1');")
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 50, "phrase": "..."}])

    assert results == []
    conn.close()

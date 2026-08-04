"""
Unit + integration tests for the Core 3000 Word Pack builder.
"""

import argparse
import sqlite3
from pathlib import Path

import pytest

from src.export.core_pack_builder import (
    CONTRACTION_MAP,
    normalize_freq_word,
    rank_to_cefr,
    select_core_words,
    select_core_words_with_gates,
)


def test_normalize_freq_word():
    assert normalize_freq_word("  DON'T  ") == "do"
    assert normalize_freq_word("I") == "i"
    assert normalize_freq_word("don") == "do"
    assert normalize_freq_word("apple") == "apple"
    assert normalize_freq_word("") == ""


def test_rank_to_cefr_thresholds():
    assert rank_to_cefr(1) == "A1"
    assert rank_to_cefr(500) == "A1"
    assert rank_to_cefr(501) == "A2"
    assert rank_to_cefr(1500) == "A2"
    assert rank_to_cefr(1501) == "B1"
    assert rank_to_cefr(3500) == "B1"
    assert rank_to_cefr(3501) == "B2"
    assert rank_to_cefr(7000) == "B2"
    assert rank_to_cefr(7001) == "C1"
    assert rank_to_cefr(15000) == "C1"
    assert rank_to_cefr(15001) == "C2"


@pytest.fixture
def small_db(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.executescript(
        """
        CREATE TABLE words (
            id INTEGER PRIMARY KEY, lemma TEXT UNIQUE, pos TEXT,
            ipa_uk TEXT, ipa_us TEXT, frequency_rank INTEGER, cefr_level TEXT
        );
        CREATE TABLE definitions (
            id INTEGER PRIMARY KEY, word_id INTEGER, definition_en TEXT,
            definition_vi TEXT, example TEXT, source TEXT
        );
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, text_en TEXT, text_vi TEXT,
            difficulty_score REAL, cefr_level TEXT, audio_path TEXT, source TEXT
        );
        CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER);
        CREATE TABLE word_topics (word_id INTEGER, topic TEXT, raw_topic TEXT);
        CREATE TABLE collocations (
            id INTEGER PRIMARY KEY, phrase TEXT, meaning_vi TEXT,
            pos_pattern TEXT, cefr_level TEXT
        );
        CREATE TABLE phrases (
            id INTEGER PRIMARY KEY, phrase TEXT, phrase_type TEXT, pos TEXT,
            cefr_level TEXT, difficulty_score REAL, definition_en TEXT,
            definition_vi TEXT, ipa TEXT, audio_std TEXT, audio_fast TEXT,
            audio_status TEXT
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_words(conn, words):
    for lemma, pos, rank in words:
        conn.execute(
            "INSERT INTO words (lemma, pos, frequency_rank, cefr_level) VALUES (?, ?, ?, 'C2')",
            (lemma, pos, rank),
        )
    conn.commit()


def test_select_core_words_filters_noise_and_ranks(tmp_path, small_db):
    # rank-1 "the" not in words; rank-2 "name" noise POS; rank-3..7 present
    _insert_words(small_db, [
        ("cat", "noun", 3),
        ("dog", "noun", 4),
        ("run", "verb", 5),
        ("John", "name", 6),
        ("happy", "adj", 7),
    ])
    freq = {"the": 1, "name": 2, "cat": 3, "dog": 4, "run": 5, "john": 6, "happy": 7}
    selected = select_core_words(small_db, freq, target=4, window=100)
    lemmas = [w["lemma"] for w in selected]
    assert lemmas == ["cat", "dog", "run", "happy"]  # noise POS "name" excluded
    assert all(w["pos"] != "name" for w in selected)


def test_select_core_words_contraction_join(tmp_path, small_db):
    _insert_words(small_db, [("do", "verb", 1)])
    freq = {"don't": 1, "does": 2, "do": 3}
    selected = select_core_words(small_db, freq, target=1, window=100)
    assert selected[0]["lemma"] == "do"  # "don't" normalizes to "do"


def test_select_core_words_respects_window(tmp_path, small_db):
    _insert_words(small_db, [("cat", "noun", 1), ("dog", "noun", 2)])
    freq = {"cat": 1, "dog": 2}
    selected = select_core_words(small_db, freq, target=5, window=2)
    assert len(selected) == 2  # window exhausted before target


def test_select_core_words_with_gates_returns_metrics(tmp_path, small_db):
    _insert_words(small_db, [
        ("the", "det", 1), ("be", "verb", 2), ("and", "conj", 3),
        ("of", "prep", 4), ("a", "det", 5),
    ])
    small_db.execute("INSERT INTO sentences (text_en, text_vi, cefr_level) VALUES ('the cat and the dog', 'con meo va con cho', 'A1')")
    small_db.commit()
    ngsl = tmp_path / "ngsl.csv"
    ngsl.write_text("the,,,\nbe,,,\nand,,,\nof,,,\na,,,\n", encoding="utf-8")

    selected, metrics = select_core_words_with_gates(
        small_db, freq_dict={"the": 1, "be": 2, "and": 3, "of": 4, "a": 5, "cat": 6},
        ngsl_path=ngsl, target=5,
    )
    assert len(selected) == 5
    assert metrics["ngsl_overlap"] == 1.0
    assert metrics["tatoeba_coverage"] >= 0.5
"""
Unit tests for PhraseExampleMatcher in src.nlp.phrase_example_matcher
"""

import pytest
from src.nlp.phrase_example_matcher import PhraseExampleMatcher


@pytest.fixture
def sentence_pool():
    return [
        {"id": 1, "text_en": "Break a leg at the show tonight!", "cefr_level": "B1"},
        {"id": 2, "text_en": "She told me to break a leg before the exam.", "cefr_level": "B2"},
        {"id": 3, "text_en": "I finally decided to give up smoking.", "cefr_level": "A2"},
        {"id": 4, "text_en": "Please do not give upward pressure to the door.", "cefr_level": "C1"},
        {"id": 5, "text_en": "He gave up the fight after ten minutes.", "cefr_level": "B1"},
        {"id": 6, "text_en": "A short unrelated sentence.", "cefr_level": "A1"}
    ]


def test_match_phrase_ranks_easy_sentences_first(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("break a leg", phrase_id=10)

    assert [r["phrase_id"] for r in result] == [10, 10]
    assert [r["sentence_id"] for r in result] == [1, 2]
    assert [r["rank"] for r in result] == [1, 2]


def test_match_phrase_boundary_rejects_partial_word(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("give up", phrase_id=20)

    # Sentence 4 contains "give upward" -> boundary mismatch, must be excluded
    sentence_ids = [r["sentence_id"] for r in result]
    assert 4 not in sentence_ids
    assert 3 in sentence_ids
    assert 5 in sentence_ids


def test_match_phrase_no_match_returns_empty(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("pull the wool over someone's eyes", phrase_id=30)
    assert result == []


def test_match_phrase_caps_at_five():
    pool = [{"id": i, "text_en": f"sample phrase number {i} here", "cefr_level": "A1"} for i in range(1, 20)]
    matcher = PhraseExampleMatcher(pool)
    result = matcher.match_phrase("sample phrase", phrase_id=40)
    assert len(result) == 5


def test_match_phrases_batch(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    phrases = [{"id": 10, "phrase": "break a leg"}, {"id": 20, "phrase": "give up"}]
    result = matcher.match_phrases(phrases)
    assert len(result) == 4
    assert {r["phrase_id"] for r in result} == {10, 20}


def test_match_phrase_inflected_phrasal_verb(sentence_pool):
    pool = sentence_pool + [
        {"id": 60, "text_en": "He strings her along with empty promises.", "cefr_level": "B2"},
        {"id": 61, "text_en": "Water springs up from the ground in that valley.", "cefr_level": "A2"},
    ]
    matcher = PhraseExampleMatcher(pool)
    result = matcher.match_phrase("string along", phrase_id=90)
    assert 60 in [r["sentence_id"] for r in result]
    result = matcher.match_phrase("spring up", phrase_id=91)
    assert 61 in [r["sentence_id"] for r in result]


def test_match_phrase_hyphen_normalization(sentence_pool):
    pool = sentence_pool + [
        {"id": 70, "text_en": "He is a well-known author.", "cefr_level": "B1"},
    ]
    matcher = PhraseExampleMatcher(pool)
    result = matcher.match_phrase("well known", phrase_id=70)
    assert 70 in [r["sentence_id"] for r in result]
    result = matcher.match_phrase("well-known", phrase_id=71)
    assert 70 in [r["sentence_id"] for r in result]

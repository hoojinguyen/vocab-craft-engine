"""
Unit tests for PhraseGrader in src.nlp.phrase_grader
"""

import pytest
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.phrase_grader import PhraseGrader


@pytest.fixture
def grader():
    freq_dict = {
        "break": 100, "leg": 300,          # both A1
        "wool": 12000, "eyes": 2000,       # wool B2, eyes A2
        "pull": 800, "someone": 1500,
        "gold": 4000, "glitters": 18000,   # gold A2, glitters C1
        "give": 50, "cat": 6000,
        "a": 1, "an": 2, "the": 3, "of": 4 # stopwords — must exist so fallback grading stays A1
    }
    cefr = CEFRGrader(freq_dict)
    return PhraseGrader(cefr)


def test_grade_phrase_easy_idiom(grader: PhraseGrader):
    result = grader.grade_phrase("break a leg")
    assert result["cefr_level"] in ("A1", "A2")
    assert result["difficulty_score"] >= 1.0


def test_grade_phrase_hard_idiom(grader: PhraseGrader):
    result = grader.grade_phrase("pull the wool over someone's eyes")
    assert result["cefr_level"] in ("B2", "C1", "C2")
    assert result["difficulty_score"] > grader.grade_phrase("break a leg")["difficulty_score"]


def test_grade_phrase_returns_expected_keys(grader: PhraseGrader):
    result = grader.grade_phrase("give up")
    assert set(result.keys()) == {"difficulty_score", "cefr_level", "word_count"}


def test_grade_phrase_all_stopwords_uses_raw_tokens(grader: PhraseGrader):
    result = grader.grade_phrase("a an the of")
    assert result["word_count"] == 4
    assert result["cefr_level"] == "A1"

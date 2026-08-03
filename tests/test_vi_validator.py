"""
Unit tests for VietnameseTextValidator in src.nlp.vi_validator
"""

import pytest
from src.nlp.vi_validator import VietnameseTextValidator


@pytest.fixture
def validator():
    return VietnameseTextValidator()


def test_accepts_toned_vietnamese(validator):
    assert validator.is_vietnamese("con chó đang chạy") is True
    assert validator.is_vietnamese("Bạn khỏe không?") is True
    assert validator.is_vietnamese("chào buổi sáng") is True


def test_accepts_vietnamese_specific_chars(validator):
    assert validator.is_vietnamese("đi học") is True
    assert validator.is_vietnamese("trường học") is True


def test_rejects_english_with_function_words(validator):
    assert validator.is_vietnamese("The quick brown fox jumps over the lazy dog") is False
    assert validator.is_vietnamese("to be or not to be") is False
    assert validator.is_vietnamese("A small furry animal that says meow") is False


def test_accepts_short_ambiguous_text(validator):
    # No diacritics, no English function words -> accept (avoid false rejects)
    assert validator.is_vietnamese("cat") is True
    assert validator.is_vietnamese("ban") is True


def test_rejects_empty_and_whitespace(validator):
    assert validator.is_vietnamese("") is False
    assert validator.is_vietnamese("   ") is False


def test_rejects_contractions_and_punctuation(validator):
    assert validator.is_vietnamese("It's a loyal animal.") is False
    assert validator.is_vietnamese("He doesn't like the weather here.") is False
    assert validator.is_vietnamese("This is the dog — it loves you.") is False


def test_accepts_vietnamese_punctuation(validator):
    assert validator.is_vietnamese("Con chó đang chạy!") is True
    assert validator.is_vietnamese("Xin chào — bạn khỏe không?") is True
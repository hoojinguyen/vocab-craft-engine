"""Tests for hybrid translator."""

import pytest
from unittest.mock import MagicMock, patch
from src.nlp.translator_hybrid import HybridTranslator


def test_uses_local_when_available():
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "Xin chào"
    translator._fallback = MagicMock()

    result = translator.translate("hello")

    assert result == "Xin chào"
    translator._fallback.translate.assert_not_called()


def test_falls_back_to_google_when_local_returns_english():
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "hello world this is a test"
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")

    assert result == "Xin chào"
    translator._fallback.translate.assert_called_once()


def test_returns_empty_when_both_fail():
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "the cat is on the mat"
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "the cat is on the mat"

    result = translator.translate("the cat is on the mat")
    assert result == ""


def test_skips_local_if_not_available():
    translator = HybridTranslator()
    translator._local = None
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")
    assert result == "Xin chào"


def test_validates_output():
    translator = HybridTranslator()
    translator._local = MagicMock()
    translator._local.translate.return_value = "the and of the and of"
    translator._fallback = MagicMock()
    translator._fallback.translate.return_value = "Xin chào"

    result = translator.translate("hello")
    assert result == "Xin chào"

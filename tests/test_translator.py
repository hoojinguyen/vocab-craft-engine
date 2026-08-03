"""
Unit tests for Translator validation behavior in src.nlp.translator
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nlp.translator import Translator


def make_translator(tmp_path: Path, fake) -> Translator:
    tr = Translator(cache_path=tmp_path / "cache.json")
    tr._translator = fake
    return tr


def test_translate_valid_vietnamese_cached(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "con chó"))
    assert tr.translate_text("dog") == "con chó"
    assert tr.translate_text("dog") == "con chó"  # served from cache


def test_translate_english_passthrough_rejected(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "The dog is an animal"))
    assert tr.translate_text("dog") == ""


def test_translate_retries_once_then_returns_empty(tmp_path: Path):
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            return "The dog is an animal"  # English -> rejected, retry
        return "con chó"

    tr = make_translator(tmp_path, SimpleNamespace(translate=flaky))
    assert tr.translate_text("dog") == "con chó"
    assert calls["n"] == 2


def test_translate_exception_returns_empty(tmp_path: Path):
    def boom(text):
        raise RuntimeError("network down")

    tr = make_translator(tmp_path, SimpleNamespace(translate=boom))
    assert tr.translate_text("dog") == ""


def test_cache_never_stores_passthrough(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "The dog is an animal"))
    tr.translate_text("dog")
    assert "dog" not in tr.cache

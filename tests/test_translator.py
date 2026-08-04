"""
Unit tests for Translator validation behavior in src.nlp.translator
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nlp.translator import Translator


def make_translator(tmp_path: Path, fake) -> Translator:
    tr = Translator(cache_path=tmp_path / "cache.json", backoff_seconds=0)
    tr._translator = fake
    return tr


def test_translate_valid_vietnamese_cached(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "con chó"))
    assert tr.translate_text("dog") == "con chó"
    assert tr.translate_text("dog") == "con chó"  # served from cache


def test_translate_english_passthrough_rejected(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "The dog is an animal"))
    assert tr.translate_text("dog") == ""


def test_translate_unchanged_text_rejected(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "Angstrom."))
    assert tr.translate_text("Angstrom.") == ""
    assert tr.translate_text("angstrom") == ""
    assert "Angstrom." not in tr.cache


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


def test_cache_polluted_entries_purged_on_load(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"dog": "The dog is an animal", "cat": "con mèo"}', encoding="utf-8")
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "con chó"))
    assert tr.translate_text("cat") == "con mèo"   # valid cache entry served
    assert tr.translate_text("dog") == "con chó"   # polluted entry purged, re-translated


def test_cache_unchanged_text_purged_on_load(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"Angstrom.": "Angstrom.", "mèo": "con mèo"}', encoding="utf-8")
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "bản dịch"))
    assert tr.translate_text("Angstrom.") == "bản dịch"  # passthrough entry purged
    assert tr.translate_text("mèo") == "con mèo"         # valid entry still served


def test_translate_backoff_between_attempts(tmp_path: Path):
    import time

    class SlowFake:
        def __init__(self):
            self.calls = 0
        def translate(self, text):
            self.calls += 1
            return "" if self.calls == 1 else "con chó"

    tr = Translator(cache_path=tmp_path / "cache.json", backoff_seconds=0.05)
    tr._translator = SlowFake()
    start = time.monotonic()
    result = tr.translate_text("dog")
    elapsed = time.monotonic() - start
    assert result == "con chó"
    assert elapsed >= 0.04  # slept between attempts

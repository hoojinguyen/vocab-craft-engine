import pytest
from src.nlp.translator import Translator


def test_async_batch_translation(monkeypatch):
    translator = Translator()

    # Mock _translate_with_timeout to return dummy Vietnamese string
    monkeypatch.setattr(translator, "_translate_with_timeout", lambda t, text: f"dịch {text}")

    items = [(1, "apple"), (2, "banana"), (3, "orange")]
    results = translator.translate_batch_async(items, max_workers=2)

    assert len(results) == 3
    assert ("dịch apple", 1) in results
    assert ("dịch banana", 2) in results
    assert ("dịch orange", 3) in results


def test_async_batch_translation_empty():
    translator = Translator()
    results = translator.translate_batch_async([], max_workers=2)
    assert results == []


def test_async_batch_translation_filters_invalid(monkeypatch):
    translator = Translator()

    def mock_translate(t, text):
        if text == "apple":
            return "quả táo"
        elif text == "banana":
            return "banana"  # passthrough/invalid vi
        return ""

    monkeypatch.setattr(translator, "_translate_with_timeout", mock_translate)

    items = [(1, "apple"), (2, "banana"), (3, "unknown")]
    results = translator.translate_batch_async(items, max_workers=2)

    assert len(results) == 1
    assert results == [("quả táo", 1)]

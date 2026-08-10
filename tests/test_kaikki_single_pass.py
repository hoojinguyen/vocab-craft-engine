"""Tests for single-pass Kaikki parser."""

import json
import pytest
from pathlib import Path
from src.ingestion.kaikki_single_pass import KaikkiSinglePassParser


@pytest.fixture
def sample_kaikki(tmp_path):
    entries = [
        {"word": "hello", "pos": "intj", "sounds": [{"ipa": "/həˈloʊ/", "tags": ["US"]}],
         "senses": [{"glosses": ["a greeting"], "examples": [{"text": "Hello world!"}]}]},
        {"word": "kick the bucket", "pos": "idiom",
         "senses": [{"glosses": ["to die"]}]},
        {"word": "happy", "pos": "adj",
         "sounds": [{"ipa": "/ˈhæpi/", "tags": ["US"]}],
         "senses": [{"glosses": ["feeling joy"]}],
         "synonyms": [{"word": "glad"}], "antonyms": [{"word": "sad"}],
         "hypernyms": [{"word": "emotion"}]},
    ]
    path = tmp_path / "test.jsonl"
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def test_single_pass_yields_words_and_phrases(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    lemmas = [w["lemma"] for w in result.words]
    assert "hello" in lemmas
    assert "happy" in lemmas
    assert "kick the bucket" not in lemmas


def test_single_pass_extracts_phrases(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    phrases = [p["phrase"] for p in result.phrases]
    assert "kick the bucket" in phrases


def test_single_pass_extracts_relations(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    rel_targets = [r["target_text"] for r in result.relations]
    assert "glad" in rel_targets
    assert "sad" in rel_targets
    assert "emotion" in rel_targets


def test_single_pass_extracts_definitions(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    hello_defs = [d for d in result.definitions if d.get("lemma") == "hello"]
    assert len(hello_defs) >= 1
    assert hello_defs[0]["definition_en"] == "a greeting"


def test_single_pass_extracts_ipa(sample_kaikki):
    parser = KaikkiSinglePassParser(sample_kaikki)
    result = parser.parse_all()
    hello = next(w for w in result.words if w["lemma"] == "hello")
    assert hello["ipa_us"] == "/həˈloʊ/"


def test_single_pass_handles_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    parser = KaikkiSinglePassParser(path)
    result = parser.parse_all()
    assert len(result.words) == 0

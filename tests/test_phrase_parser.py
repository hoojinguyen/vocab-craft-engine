"""
Unit tests for PhraseParser and KaikkiParser raw streaming
"""

import json
import pytest
from pathlib import Path
from src.ingestion.kaikki_parser import KaikkiParser
from src.ingestion.phrase_parser import PhraseParser


@pytest.fixture
def kaikki_jsonl(tmp_path: Path) -> Path:
    entries = [
        {
            "word": "break a leg",
            "pos": "idiom",
            "sounds": [{"ipa": "breɪk ə leɡ", "tags": ["US"]}],
            "translations": [{"code": "vi", "word": "chúc may mắn"}],
            "senses": [{"glosses": ["A phrase of encouragement."]}]
        },
        {
            "word": "give up",
            "pos": "phrasal verb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["To stop trying."]}]
        },
        {
            "word": "all that glitters is not gold",
            "pos": "proverb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Appearances are deceptive."]}]
        },
        {
            "word": "cat",
            "pos": "noun",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["A small furry animal."]}]
        },
        {
            "word": "too many cooks spoil the broth",
            "pos": "proverb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Too many people on a task."]}]
        },
        {
            "word": "a very long multi word expression that nobody uses at all",
            "pos": "phrase",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Nonsense."]}]
        },
        {
            "word": "no definition here",
            "pos": "idiom",
            "sounds": [],
            "translations": [],
            "senses": []
        },
        {
            "word": "break 1 leg",
            "pos": "idiom",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Contains a digit, must be rejected."]}]
        }
    ]
    f = tmp_path / "kaikki_sample.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return f


def test_parse_raw_items_yields_unfiltered_dicts(kaikki_jsonl: Path):
    parser = KaikkiParser(kaikki_jsonl)
    items = list(parser.parse_raw_items())
    assert len(items) == 8
    assert items[0]["word"] == "break a leg"
    assert items[3]["word"] == "cat"


def test_phrase_parser_extracts_only_valid_multiword(kaikki_jsonl: Path):
    parser = PhraseParser(kaikki_jsonl)
    phrases = list(parser.parse_phrases())

    by_phrase = {p["phrase"]: p for p in phrases}
    assert "break a leg" in by_phrase
    assert "give up" in by_phrase
    assert "all that glitters is not gold" in by_phrase

    # Reject single-word, >6 word non-proverb, no-definition entries
    assert "cat" not in by_phrase
    assert "a very long multi word expression that nobody uses at all" not in by_phrase
    assert "no definition here" not in by_phrase

    # Proverb longer than 6 words IS kept
    assert "too many cooks spoil the broth" in by_phrase

    # Field extraction
    leg = by_phrase["break a leg"]
    assert leg["phrase_type"] == "idiom"
    assert leg["definition_en"] == "A phrase of encouragement."
    assert leg["definition_vi"] == "chúc may mắn"
    assert leg["ipa"] == "breɪk ə leɡ"

    up = by_phrase["give up"]
    assert up["phrase_type"] == "phrasal_verb"


def test_phrase_parser_rejects_unclean_chars(kaikki_jsonl: Path):
    parser = PhraseParser(kaikki_jsonl)
    # "break 1 leg" contains a digit -> must be rejected (quality filter)
    phrases = list(parser.parse_phrases())
    by_phrase = {p["phrase"]: p for p in phrases}
    assert "break 1 leg" not in by_phrase

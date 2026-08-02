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

"""
Unit tests for Ingestion Parsers (Kaikki, Tatoeba, OPUS) in src.ingestion
"""

import json
import pytest
from pathlib import Path
from src.ingestion.kaikki_parser import KaikkiParser
from src.ingestion.tatoeba_parser import TatoebaParser
from src.ingestion.opus_parser import OpusParser


def test_kaikki_parser_json_array(tmp_path: Path):
    sample_data = [
        {
            "word": "run",
            "pos": "verb",
            "sounds": [{"ipa": "rʌn", "tags": ["US"]}],
            "senses": [{"glosses": ["To move fast on foot."], "examples": [{"text": "He runs fast."}]}]
        },
        {
            "word": "make progress",  # Should be skipped by single-word filter
            "pos": "phrase",
            "senses": [{"glosses": ["To improve."]}],
        }
    ]

    json_file = tmp_path / "kaikki_sample.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(sample_data, f)

    parser = KaikkiParser(json_file)
    results = list(parser.parse_stream())

    assert len(results) == 1
    assert results[0]["lemma"] == "run"
    assert results[0]["pos"] == "verb"
    assert results[0]["ipa_us"] == "rʌn"
    assert len(results[0]["definitions"]) == 1
    assert results[0]["definitions"][0]["definition_en"] == "To move fast on foot."


def test_kaikki_parser_json_lines(tmp_path: Path):
    sample_item = {
        "word": "apple",
        "pos": "noun",
        "sounds": [{"ipa": "ˈæp.əl", "tags": ["UK"]}],
        "senses": [{"glosses": ["A round fruit."]}]
    }

    jsonl_file = tmp_path / "kaikki_sample.jsonl"
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(sample_item) + "\n")

    parser = KaikkiParser(jsonl_file)
    results = list(parser.parse_stream())

    assert len(results) == 1
    assert results[0]["lemma"] == "apple"
    assert results[0]["ipa_uk"] == "ˈæp.əl"


def test_tatoeba_parser(tmp_path: Path):
    sentences_file = tmp_path / "sentences.csv"
    links_file = tmp_path / "links.csv"

    # Write sentences.csv: id \t lang \t text
    with open(sentences_file, "w", encoding="utf-8") as f:
        f.write("1\teng\tHello, how are you?\n")
        f.write("2\tvie\tXin chào, bạn khỏe không?\n")

    # Write links.csv: id1 \t id2
    with open(links_file, "w", encoding="utf-8") as f:
        f.write("1\t2\n")

    parser = TatoebaParser(sentences_file, links_file)
    pairs = list(parser.parse_aligned_pairs())

    assert len(pairs) == 1
    assert pairs[0]["text_en"] == "Hello, how are you?"
    assert pairs[0]["text_vi"] == "Xin chào, bạn khỏe không?"
    assert pairs[0]["source"] == "Tatoeba"


def test_opus_parser_tsv_alias(tmp_path: Path):
    opus_file = tmp_path / "opensubtitles_sample.txt"
    with open(opus_file, "w", encoding="utf-8") as f:
        f.write("Where are you going?\tBạn đang đi đâu thế?\n")
        f.write("123456\tIgnored number line\n")
        f.write("Yes, I agree.\tTôi đồng ý.\n")

    parser = OpusParser(tsv_path=opus_file)
    turns = list(parser.parse_pairs())

    assert len(turns) == 3
    assert turns[0]["text_en"] == "Where are you going?"
    assert turns[0]["text_vi"] == "Bạn đang đi đâu thế?"
    assert turns[0]["source"] == "OpenSubtitles"


def test_extract_fields_definition_vi_none_without_vietnamese_translation():
    item = {
        "word": "dog",
        "pos": "noun",
        "sounds": [],
        "translations": [],  # no Vietnamese translations
        "senses": [{"glosses": ["A loyal animal."]}]
    }
    parsed = KaikkiParser.extract_fields(item)
    assert parsed["vi_translations"] is None
    assert parsed["definitions"][0]["definition_vi"] is None


def test_parse_stream_unified(tmp_path: Path):
    kaikki_file = tmp_path / "kaikki_sample.json"
    sample_entry = {
        "word": "abandon",
        "pos": "verb",
        "sounds": [{"ipa": "/əˈbændən/", "tags": ["UK"]}],
        "senses": [{"glosses": ["To give up completely."], "tags": []}],
        "relations": [{"type": "synonym", "word": "relinquish"}],
        "topics": ["psychology"]
    }
    kaikki_file.write_text(json.dumps(sample_entry) + "\n", encoding="utf-8")

    parser = KaikkiParser(kaikki_file)
    records = list(parser.parse_stream_unified())
    assert len(records) == 1
    rec = records[0]
    assert rec["lemma"] == "abandon"
    assert rec["pos"] == "verb"
    assert len(rec["definitions"]) == 1
    assert len(rec["relations"]) == 1
    assert len(rec["topics"]) == 1


def test_parse_stream_unified_null_fields_and_string_relations(tmp_path: Path):
    null_word_entry = {"word": None, "pos": "verb"}
    null_pos_entry = {
        "word": "abandon",
        "pos": None,
        "synonyms": ["relinquish", {"word": "forsake"}]
    }
    kaikki_file = tmp_path / "kaikki_null_sample.jsonl"
    with open(kaikki_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(null_word_entry) + "\n")
        f.write(json.dumps(null_pos_entry) + "\n")

    parser = KaikkiParser(kaikki_file)
    records = list(parser.parse_stream_unified())
    assert len(records) == 1
    rec = records[0]
    assert rec["lemma"] == "abandon"
    assert rec["pos"] == "noun"
    targets = {r["target"] for r in rec["relations"]}
    assert targets == {"relinquish", "forsake"}



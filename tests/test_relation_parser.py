"""
Tests for RelationParser in src.ingestion.relation_parser
"""

import json
import pytest
from pathlib import Path
from src.ingestion.relation_parser import RelationParser


def test_extract_relations_dedupe_and_filter():
    entry = {
        "word": "Dog",
        "pos": "noun",
        "senses": [{"glosses": ["An animal."], "topics": ["zoology", "zoology"]}],
        "synonyms": [{"word": "hound"}, {"word": "1.5"}],
        "hypernyms": [{"word": "animal"}, {"word": "animal"}],
        "antonyms": [{"word": "cat"}]
    }
    parsed = RelationParser.extract_entry_fields(entry)

    assert parsed["word"] == "dog"
    rel_types = {(r["relation_type"], r["target"]) for r in parsed["relations"]}
    assert ("synonym", "hound") in rel_types
    assert ("hypernym", "animal") in rel_types
    assert ("antonym", "cat") in rel_types
    # Bad target (digit) rejected
    assert not any(r["target"] == "1.5" for r in parsed["relations"])
    # Dedupe across senses: "animal" appears once
    assert sum(1 for r in parsed["relations"] if r["target"] == "animal") == 1
    # Topics mapped + deduped
    assert parsed["topics"] == [{"topic": "Nature & Animals", "raw_topic": "zoology"}]


def test_extract_self_reference_dropped():
    parsed = RelationParser.extract_entry_fields({
        "word": "dog",
        "pos": "noun",
        "senses": [],
        "synonyms": [{"word": "dog"}]
    })
    assert parsed is None  # relation dropped, no topics → nothing yielded


def test_extract_rejects_multi_word_entry():
    parsed = RelationParser.extract_entry_fields({
        "word": "break a leg",
        "pos": "idiom",
        "senses": [],
        "synonyms": []
    })
    assert parsed is None


def test_extract_caps_targets_per_type():
    entry = {
        "word": "dog",
        "pos": "noun",
        "senses": [],
        "synonyms": [{"word": "synonym" + "a" * (i + 1)} for i in range(30)]
    }
    parsed = RelationParser.extract_entry_fields(entry)
    synonyms = [r for r in parsed["relations"] if r["relation_type"] == "synonym"]
    assert len(synonyms) == 25


def test_parse_entries_streams_only_yielding_entries(tmp_path: Path):
    file = tmp_path / "kaikki.jsonl"
    file.write_text("\n".join(json.dumps(e) for e in [
        {"word": "dog", "pos": "noun", "senses": [{"topics": ["zoology"]}],
         "synonyms": [{"word": "hound"}]},
        {"word": "run", "pos": "noun", "senses": [], "synonyms": []},
        {"word": "cat", "pos": "noun", "senses": [], "antonyms": [{"word": "dog"}]}
    ]), encoding="utf-8")

    rows = list(RelationParser(file).parse_entries())
    assert [r["word"] for r in rows] == ["dog", "cat"]

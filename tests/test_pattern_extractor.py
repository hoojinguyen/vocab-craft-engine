import pytest
import spacy
from src.nlp.pattern_extractor import GrammarPatternExtractor

def test_extract_it_is_adj_to_v():
    extractor = GrammarPatternExtractor()
    patterns = extractor.extract_patterns("It is easy to learn English.")
    assert len(patterns) >= 1
    names = [p["pattern_name"] for p in patterns]
    assert "it_is_adj_to_v" in names
    match = next(p for p in patterns if p["pattern_name"] == "it_is_adj_to_v")
    assert match["cefr_level"] == "A2"

def test_extract_would_mind_ving():
    extractor = GrammarPatternExtractor()
    patterns = extractor.extract_patterns("Would you mind opening the door?")
    names = [p["pattern_name"] for p in patterns]
    assert "would_mind_ving" in names
    match = next(p for p in patterns if p["pattern_name"] == "would_mind_ving")
    assert match["cefr_level"] == "B1"

def test_extract_with_spacy_doc():
    extractor = GrammarPatternExtractor()
    doc = extractor.nlp("It is hard to master programming.")
    patterns = extractor.extract_patterns(doc)
    assert len(patterns) >= 1
    names = [p["pattern_name"] for p in patterns]
    assert "it_is_adj_to_v" in names

def test_extract_dependency_matcher():
    extractor = GrammarPatternExtractor()
    # Sentence with an adverb ("remarkably") which skips standard token sequence matcher
    patterns = extractor.extract_patterns("It is remarkably easy to learn English.")
    names = [p["pattern_name"] for p in patterns]
    assert "it_is_adj_to_v" in names
    match = next(p for p in patterns if p["pattern_name"] == "it_is_adj_to_v")
    assert match["cefr_level"] == "A2"
    assert "It is remarkably easy to learn" in match["structure_json"]

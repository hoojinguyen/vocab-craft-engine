import pytest
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

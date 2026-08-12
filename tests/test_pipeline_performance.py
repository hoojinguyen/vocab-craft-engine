import pytest
from src.nlp.parallel_processor import ParallelProcessor

def test_parallel_processor_lemmatization():
    sentences = [
        (1, "The quick brown fox jumps over the lazy dog."),
        (2, "She decided to learn Python programming.")
    ]
    processor = ParallelProcessor(max_workers=2, disable_parallel=False)
    results = processor.process_sentence_lemmatization(sentences)
    assert len(results) >= 10
    lemmas = {r["lemma"] for r in results}
    assert "fox" in lemmas
    assert "jump" in lemmas or "jumps" in lemmas

def test_parallel_processor_no_parallel_flag():
    sentences = [(1, "Hello world.")]
    processor = ParallelProcessor(disable_parallel=True)
    results = processor.process_sentence_lemmatization(sentences)
    assert len(results) >= 2

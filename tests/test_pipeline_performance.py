import pytest
from src.nlp.parallel_processor import ParallelProcessor


def test_parallel_processor_lemmatization():
    sentences = [
        (1, "The quick brown fox jumps over the lazy dog."),
        (2, "She decided to learn Python programming.")
    ]
    with ParallelProcessor(max_workers=2, disable_parallel=False) as processor:
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
    assert processor._executor is None
    processor.close()


def test_parallel_processor_persistent_executor_reuse():
    sentences_chunk1 = [(1, "First chunk sentence test.")]
    sentences_chunk2 = [(2, "Second chunk sentence test.")]

    with ParallelProcessor(max_workers=2, disable_parallel=False) as processor:
        res1 = processor.process_sentence_lemmatization(sentences_chunk1)
        assert len(res1) > 0
        executor1 = processor._executor
        assert executor1 is not None

        # Process second chunk on same processor instance
        res2 = processor.process_sentence_lemmatization(sentences_chunk2)
        assert len(res2) > 0
        executor2 = processor._executor
        # Verify same executor instance is reused
        assert executor1 is executor2

    # Context manager exit should close executor
    assert processor._executor is None


def test_parallel_processor_pattern_extraction():
    sentences = [(1, "It is easy to learn English.", "Rất dễ để học tiếng Anh.")]
    with ParallelProcessor(max_workers=2, disable_parallel=False) as processor:
        results = processor.process_pattern_extraction(sentences)
        assert len(results) >= 1
        assert processor._executor is not None
    assert processor._executor is None



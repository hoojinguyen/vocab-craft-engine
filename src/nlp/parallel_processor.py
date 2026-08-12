"""
Multi-Core Parallel NLP Processor.
Uses ProcessPoolExecutor to distribute NLP lemmatization and pattern extraction tasks across available CPU cores.
"""

import os
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import List, Dict, Any, Tuple, Optional, Union
from src.nlp.lemmatizer import Lemmatizer
from src.nlp.pattern_extractor import GrammarPatternExtractor

logger = logging.getLogger(__name__)

_worker_lemmatizer: Optional[Lemmatizer] = None
_worker_pattern_extractor: Optional[GrammarPatternExtractor] = None


def _init_lemmatizer_worker():
    global _worker_lemmatizer
    _worker_lemmatizer = Lemmatizer()


def _process_lemmatization_chunk(sentences_chunk: List[Union[Tuple[int, str], Dict[str, Any]]]) -> List[Dict[str, Any]]:
    global _worker_lemmatizer
    if _worker_lemmatizer is None:
        _worker_lemmatizer = Lemmatizer()

    results = []
    for item in sentences_chunk:
        if isinstance(item, (tuple, list)):
            s_id, text_en = item[0], item[1]
        elif isinstance(item, dict):
            s_id, text_en = item.get("id"), item.get("text_en")
        else:
            continue

        if not text_en:
            continue

        tokens = _worker_lemmatizer.lemmatize_text(text_en)
        for token_info in tokens:
            results.append({
                "sentence_id": s_id,
                "lemma": token_info["lemma"],
                "text": token_info.get("text"),
                "pos": token_info.get("pos")
            })
    return results


def _init_pattern_worker():
    global _worker_pattern_extractor
    _worker_pattern_extractor = GrammarPatternExtractor()


def _process_pattern_chunk(sentences_chunk: List[Union[Tuple[int, str, Optional[str]], Dict[str, Any]]]) -> List[Dict[str, Any]]:
    global _worker_pattern_extractor
    if _worker_pattern_extractor is None:
        _worker_pattern_extractor = GrammarPatternExtractor()

    results = []
    for item in sentences_chunk:
        if isinstance(item, (tuple, list)):
            s_id = item[0]
            text_en = item[1]
            text_vi = item[2] if len(item) > 2 else None
        elif isinstance(item, dict):
            s_id = item.get("id")
            text_en = item.get("text_en")
            text_vi = item.get("text_vi")
        else:
            continue

        if not text_en:
            continue

        matches = _worker_pattern_extractor.extract_patterns(text_en)
        for match in matches:
            results.append({
                "sentence_id": s_id,
                "pattern_name": match["pattern_name"],
                "structure_json": match["structure_json"],
                "matched_tokens_json": match["matched_tokens_json"],
                "cefr_level": match["cefr_level"],
                "example_en": text_en,
                "example_vi": text_vi
            })
    return results


class ParallelProcessor:
    """Multi-Core Parallel NLP Processor using ProcessPoolExecutor."""

    def __init__(self, max_workers: Optional[int] = None, disable_parallel: bool = False):
        self.disable_parallel = disable_parallel
        cpus = os.cpu_count() or 4
        self.max_workers = max(1, max_workers if max_workers is not None else min(cpus, 8))
        self._executor: Optional[ProcessPoolExecutor] = None
        self._initializer = None

    def _get_executor(self, initializer=None) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self.max_workers,
                initializer=initializer
            )
            self._initializer = initializer
        return self._executor

    def close(self) -> None:
        """Shuts down the persistent ProcessPoolExecutor if active."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
            self._initializer = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def process_sentence_lemmatization(
        self,
        sentences: List[Union[Tuple[int, str], Dict[str, Any]]],
        chunk_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Processes sentence lemmatization across multiple worker processes.
        """
        if not sentences:
            return []

        if self.disable_parallel or self.max_workers <= 1:
            return _process_lemmatization_chunk(sentences)

        if chunk_size is None:
            num_chunks = self.max_workers * 4
            chunk_size = max(1, len(sentences) // num_chunks)

        chunks = [sentences[i:i + chunk_size] for i in range(0, len(sentences), chunk_size)]

        results = []
        executor = self._get_executor(initializer=_init_lemmatizer_worker)
        for chunk_res in executor.map(_process_lemmatization_chunk, chunks):
            results.extend(chunk_res)

        return results

    def process_pattern_extraction(
        self,
        sentences: List[Union[Tuple[int, str, Optional[str]], Dict[str, Any]]],
        chunk_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Processes grammar pattern extraction across multiple worker processes.
        """
        if not sentences:
            return []

        if self.disable_parallel or self.max_workers <= 1:
            return _process_pattern_chunk(sentences)

        if chunk_size is None:
            num_chunks = self.max_workers * 4
            chunk_size = max(1, len(sentences) // num_chunks)

        chunks = [sentences[i:i + chunk_size] for i in range(0, len(sentences), chunk_size)]

        results = []
        executor = self._get_executor(initializer=_init_pattern_worker)
        for chunk_res in executor.map(_process_pattern_chunk, chunks):
            results.extend(chunk_res)

        return results


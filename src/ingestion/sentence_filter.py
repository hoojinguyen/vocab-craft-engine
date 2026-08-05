"""Noise filtering for parallel sentence corpora (spec §4.3)."""

import re
import string

class SentenceFilter:
    MIN_WORDS = 2
    MAX_WORDS = 30

    _NOISE_PATTERNS = re.compile(
        r"♪|^\[|^\(|\*.*\*$|^[A-Z]{2,15}:\s"  # music, brackets, parens, asterisks, name labels
    )
    _DIGIT_RATIO = 0.15

    @staticmethod
    def _is_passthrough(text_en: str, text_vi: str) -> bool:
        norm = lambda s: s.strip().strip(".").strip().lower()
        return bool(norm(text_en)) and norm(text_en) == norm(text_vi)

    def is_clean_pair(self, text_en: str, text_vi: str) -> bool:
        if not text_en or not text_vi:
            return False
        words = text_en.split()
        if not (self.MIN_WORDS <= len(words) <= self.MAX_WORDS):
            return False
        if not text_en[0].isalnum() and text_en[0] not in ('"', "'"):
            return False
        if self._is_passthrough(text_en, text_vi):
            return False
        if self._NOISE_PATTERNS.search(text_en):
            return False
        digits = sum(c.isdigit() for c in text_en)
        if len(text_en) > 0 and digits / len(text_en) > self._DIGIT_RATIO:
            return False
        return True

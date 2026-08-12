"""Noise filtering for parallel sentence corpora."""

import re


def _normalize(s: str) -> str:
    return s.strip().strip(".").strip().lower()


class SentenceFilter:
    """Noise filtering for parallel sentence corpora."""

    MIN_WORDS = 2
    MAX_WORDS = 30
    MIN_RATIO = 0.5
    MAX_RATIO = 2.0

    _NOISE_PATTERNS = re.compile(
        r"♪|^\[|^\(|\*.*\*$|^[A-Z]{2,15}:\s"  # music, brackets, parens, asterisks, name labels
    )
    _VIETNAMESE_DIACRITICS = re.compile(
        r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]"
    )
    _DIGIT_RATIO = 0.15

    @staticmethod
    def _is_passthrough(text_en: str, text_vi: str) -> bool:
        return bool(_normalize(text_en)) and _normalize(text_en) == _normalize(text_vi)

    def is_clean_pair(self, text_en: str, text_vi: str) -> bool:
        if not text_en or not text_vi:
            return False
        words_en = text_en.split()
        words_vi = text_vi.split()

        if not (self.MIN_WORDS <= len(words_en) <= self.MAX_WORDS):
            return False

        # Length ratio guard
        ratio = len(words_vi) / len(words_en) if len(words_en) > 0 else 0
        if not (self.MIN_RATIO <= ratio <= self.MAX_RATIO):
            return False

        if not text_en[0].isalnum() and text_en[0] not in ('"', "'"):
            return False
        if self._is_passthrough(text_en, text_vi):
            return False
        if self._NOISE_PATTERNS.search(text_en):
            return False

        # Vietnamese diacritics guard for sentences > 3 words
        if len(words_vi) > 3 and not self._VIETNAMESE_DIACRITICS.search(text_vi.lower()):
            return False

        digits = sum(c.isdigit() for c in text_en)
        if digits / len(text_en) > self._DIGIT_RATIO:
            return False
        return True

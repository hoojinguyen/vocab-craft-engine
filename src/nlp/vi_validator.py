"""
Vietnamese Text Validator for English Dataset System Engine.
Pure heuristic (no I/O, no network) that decides whether a text is Vietnamese.
Used to reject English passthrough from machine translation providers.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_WORD_SPLIT = re.compile(r"[^a-zà-ỹ]+")


class VietnameseTextValidator:
    """Heuristic validator: Vietnamese-specific chars or tone marks win; otherwise
    English function-word density decides."""

    # Letters that only appear in Vietnamese (plus tone-marked vowels)
    VIETNAMESE_SPECIFIC_CHARS = set("ăâđêôơư")
    TONE_MARKED_VOWELS = set("àáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ")
    ENGLISH_FUNCTION_WORDS = {
        "the", "and", "of", "to", "with", "for", "is", "are",
        "a", "an", "this", "that", "you", "in", "on", "it", "as",
        "he"
    }

    def is_vietnamese(self, text: Optional[str]) -> bool:
        """True if text is (very likely) Vietnamese, False if it is English passthrough."""
        if not text or not text.strip():
            return False

        clean = text.strip().lower()

        # 1. Vietnamese-specific characters or tone-marked vowels -> accept
        if any(ch in self.VIETNAMESE_SPECIFIC_CHARS for ch in clean) or \
           any(ch in self.TONE_MARKED_VOWELS for ch in clean):
            return True

        # 2. Split on non-letters (handles contractions, dashes, punctuation)
        tokens = [w for w in _WORD_SPLIT.split(clean) if w]
        function_word_hits = sum(1 for w in tokens if w in self.ENGLISH_FUNCTION_WORDS)
        if function_word_hits >= 2:
            return False

        # 3. Ambiguous short text -> accept (avoid false rejects)
        return True

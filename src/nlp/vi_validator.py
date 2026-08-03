"""
Vietnamese Text Validator for English Dataset System Engine.
Pure heuristic (no I/O, no network) that decides whether a text is Vietnamese.
Used to reject English passthrough from machine translation providers.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VietnameseTextValidator:
    """Heuristic validator: Vietnamese-specific chars or tone marks win; otherwise
    English function-word density decides."""

    # Letters that only appear in Vietnamese (plus tone-marked vowels)
    VIETNAMESE_SPECIFIC_CHARS = set("ăâđêôơư")
    TONE_MARKED_VOWELS = set("àáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ")
    ENGLISH_FUNCTION_WORDS = {
        "the", "and", "of", "to", "with", "for", "is", "are",
        "a", "an", "this", "that", "you", "in", "on", "it", "as"
    }

    def is_vietnamese(self, text: Optional[str]) -> bool:
        """True if text is (very likely) Vietnamese, False if it is English passthrough."""
        if not text or not text.strip():
            return False

        clean = text.strip()

        # 1. Vietnamese-specific characters or tone-marked vowels -> accept
        if any(ch in self.VIETNAMESE_SPECIFIC_CHARS for ch in clean) or \
           any(ch in self.TONE_MARKED_VOWELS for ch in clean):
            return True

        # 2. Pure ASCII: count English function words -> reject if >= 2
        function_word_hits = sum(
            1 for w in clean.split()
            if w.strip(".,!?;:\"'()[]").lower() in self.ENGLISH_FUNCTION_WORDS
        )
        if function_word_hits >= 2:
            return False

        # 3. Ambiguous short text -> accept (avoid false rejects)
        return True

"""
CEFR Phrase Grader for English Dataset System Engine.
Grades multi-word expressions using constituent word frequency ranks (reuses CEFRGrader).
"""

import logging
from typing import Dict, Any, Set

from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "by",
    "from", "up", "down", "out", "off", "over", "under", "and", "or", "but",
    "be", "is", "are", "was", "were", "do", "does", "did", "have", "has",
    "had", "as", "so", "if", "it", "its", "my", "your", "his", "her",
    "our", "their", "me", "you", "him", "us", "them", "not", "no", "yes"
}


class PhraseGrader:
    """Assigns CEFR levels and difficulty scores to multi-word expressions."""

    def __init__(self, cefr_grader: CEFRGrader, stopwords: Set[str] = STOPWORDS):
        self.cefr_grader = cefr_grader
        self.stopwords = stopwords

    def grade_phrase(self, phrase: str) -> Dict[str, Any]:
        """
        Grades a phrase from its constituent content words.
        Returns {'cefr_level', 'difficulty_score', 'word_count'} —
        same shape as CEFRGrader.grade_sentence.
        """
        tokens = [w.lower().strip(".,!?;:\"'()[]-") for w in phrase.split()]
        content_words = [w for w in tokens if w and w not in self.stopwords]
        if not content_words:
            content_words = tokens

        return self.cefr_grader.grade_sentence(" ".join(content_words))

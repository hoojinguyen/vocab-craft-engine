"""
Automatic CEFR Difficulty Grader for English Dataset System Engine.
Grades words and sentences into A1, A2, B1, B2, C1, C2 based on frequency ranks.
"""

import math
import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from config.settings import SUBTLEX_FREQ_PATH

logger = logging.getLogger(__name__)


class CEFRGrader:
    """Assigns CEFR levels to words and calculates overall sentence difficulty scores."""

    # Frequency rank thresholds
    RANK_THRESHOLDS = {
        "A1": 1000,
        "A2": 2500,
        "B1": 5000,
        "B2": 10000,
        "C1": 20000
    }

    LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

    def __init__(self, frequency_dict: Optional[Dict[str, int]] = None, subtlex_path: Optional[Path] = None):
        """
        frequency_dict: mapping of word -> frequency_rank (1 = most common).
        """
        self.freq_dict: Dict[str, int] = frequency_dict or {}
        if not self.freq_dict:
            target_path = subtlex_path or SUBTLEX_FREQ_PATH
            if target_path and target_path.exists() and target_path.stat().st_size > 0:
                self.load_subtlex(target_path)

    def load_subtlex(self, file_path: Path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader, 1):
                    w = (row.get("Word") or row.get("word") or "").strip().lower()
                    r_str = row.get("rank")
                    rank = int(r_str) if r_str and r_str.isdigit() else i
                    if w and w not in self.freq_dict:
                        self.freq_dict[w] = rank
            logger.info("Loaded %d word frequency ranks into CEFRGrader.", len(self.freq_dict))
        except Exception as e:
            logger.warning("Failed to load SUBTLEX file at %s: %s", file_path, e)

    def grade_word(self, word: str, rank: Optional[int] = None) -> Tuple[str, int]:
        """
        Returns (cefr_level, frequency_rank) for a given word.
        """
        clean_word = word.lower().strip()
        r = rank if rank is not None else self.freq_dict.get(clean_word, 25000)

        if r <= self.RANK_THRESHOLDS["A1"]:
            level = "A1"
        elif r <= self.RANK_THRESHOLDS["A2"]:
            level = "A2"
        elif r <= self.RANK_THRESHOLDS["B1"]:
            level = "B1"
        elif r <= self.RANK_THRESHOLDS["B2"]:
            level = "B2"
        elif r <= self.RANK_THRESHOLDS["C1"]:
            level = "C1"
        else:
            level = "C2"

        return level, r

    def grade_sentence(self, sentence_text: str) -> Dict[str, Any]:
        """
        Calculates difficulty score and CEFR level for a sentence based on constituent words.
        Difficulty score is a normalized logarithmic value from 1.0 (easiest) to 6.0 (hardest).
        """
        words = [w.lower().strip(".,!?;:\"'()[]") for w in sentence_text.split() if w.isalpha()]
        if not words:
            return {"difficulty_score": 1.0, "cefr_level": "A1", "word_count": 0}

        word_scores = []
        max_word_level = "A1"

        for w in words:
            lvl, rank = self.grade_word(w)
            score = math.log10(rank + 1)
            word_scores.append(score)

            if self.LEVEL_ORDER.index(lvl) > self.LEVEL_ORDER.index(max_word_level):
                max_word_level = lvl

        avg_score = sum(word_scores) / len(word_scores)

        # Grade sentence by combining average score and max non-trivial word level
        if avg_score >= 4.3 or max_word_level == "C2":
            sentence_cefr = "C2"
        elif avg_score >= 3.8 or max_word_level == "C1":
            sentence_cefr = "C1"
        elif avg_score >= 3.3 or max_word_level == "B2":
            sentence_cefr = "B2"
        elif avg_score >= 2.8 or max_word_level == "B1":
            sentence_cefr = "B1"
        elif avg_score >= 2.1 or max_word_level == "A2":
            sentence_cefr = "A2"
        else:
            sentence_cefr = "A1"

        return {
            "difficulty_score": round(avg_score, 2),
            "cefr_level": sentence_cefr,
            "word_count": len(words)
        }

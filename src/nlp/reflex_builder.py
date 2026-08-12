"""
Reflex Drill Generator for English Dataset System Engine.
Pre-generates POS & CEFR matched distractor choices for speed drills (< 2.5s response target).
"""

import json
import random
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy-loaded spaCy model
_nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    return _nlp


class ReflexBuilder:
    """Generates speed reaction drill cards with pre-computed smart distractors."""

    def __init__(self, sentence_pool: Optional[List[Dict[str, Any]]] = None):
        self.sentence_pool = sentence_pool or []
        self._rebuild_indices()

    def set_sentence_pool(self, sentence_pool: List[Dict[str, Any]]):
        self.sentence_pool = sentence_pool
        self._rebuild_indices()

    def _rebuild_indices(self):
        self.vi_pool = [s["text_vi"] for s in self.sentence_pool if s.get("text_vi")]
        # Group sentences by CEFR level
        self.cefr_pool: Dict[str, List[Dict[str, Any]]] = {}
        for s in self.sentence_pool:
            level = s.get("cefr_level", "B1")
            self.cefr_pool.setdefault(level, []).append(s)

    def build_drill(self, target_sentence: Dict[str, Any], drill_type: str = "speed_translation") -> Dict[str, Any]:
        sentence_id = target_sentence.get("id", 1)
        text_en = target_sentence.get("text_en", "")
        text_vi = target_sentence.get("text_vi", "")
        cefr_level = target_sentence.get("cefr_level", "B1")

        if drill_type == "missing_chunk_fill":
            words = text_en.split()
            if len(words) >= 3:
                missing_idx = len(words) // 2
                target_word = words[missing_idx].strip(".,!?")
                words[missing_idx] = "___"
                prompt_text = " ".join(words)
                correct_answer = target_word
                distractors = self._generate_pos_distractors(target_word, cefr_level=cefr_level, count=3)
            else:
                prompt_text = text_en
                correct_answer = text_vi
                distractors = self._generate_distractors(target_sentence, cefr_level=cefr_level, count=3)
        elif drill_type == "speed_translation":
            prompt_text = text_en
            correct_answer = text_vi
            distractors = self._generate_distractors(target_sentence, cefr_level=cefr_level, count=3)
        else:  # audio_shadowing
            prompt_text = text_en
            correct_answer = text_en
            distractors = self._generate_distractors(target_sentence, cefr_level=cefr_level, count=3)

        return {
            "sentence_id": sentence_id,
            "drill_type": drill_type,
            "prompt_text": prompt_text,
            "correct_answer": correct_answer,
            "distractors_json": json.dumps(distractors, ensure_ascii=False),
            "target_time_ms": 2500
        }

    def _generate_pos_distractors(self, target_word: str, cefr_level: str, count: int = 3) -> List[str]:
        """Generate word distractors matching target word's POS tag."""
        nlp = get_nlp()
        doc = nlp(target_word)
        target_pos = doc[0].pos_ if len(doc) > 0 else "NOUN"

        # Fallback pool of words by POS tag
        pos_fallback = {
            "VERB": ["take", "make", "find", "call", "try", "need", "keep", "look"],
            "NOUN": ["time", "person", "way", "day", "thing", "man", "world", "life"],
            "ADJ": ["good", "new", "first", "last", "long", "great", "little", "own"],
            "ADV": ["fast", "well", "also", "back", "even", "still", "down", "never"],
        }
        candidates = [w for w in pos_fallback.get(target_pos, pos_fallback["NOUN"]) if w.lower() != target_word.lower()]
        return random.sample(candidates, min(count, len(candidates)))

    def _generate_distractors(self, target_sentence: Dict[str, Any], cefr_level: str, count: int = 3) -> List[str]:
        """Generate sentence distractors matching target sentence CEFR level and word length."""
        target_vi = target_sentence.get("text_vi", "")
        target_words = len(target_vi.split())

        # Filter candidates by same CEFR level and length proximity (±25%)
        pool = self.cefr_pool.get(cefr_level, self.sentence_pool)
        candidates = [
            s["text_vi"] for s in pool
            if s.get("text_vi") and s["text_vi"] != target_vi
            and abs(len(s["text_vi"].split()) - target_words) <= max(2, int(target_words * 0.25))
        ]

        if len(candidates) >= count:
            return random.sample(candidates, count)

        # Fallback to general pool if CEFR-filtered candidates insufficient
        fallback_candidates = [s for s in self.vi_pool if s != target_vi]
        if len(fallback_candidates) >= count:
            return random.sample(fallback_candidates, count)

        static_fallbacks = [
            "Tôi hiểu rồi.",
            "Cảm ơn bạn rất nhiều.",
            "Hẹn gặp lại bạn sau.",
            "Xin lỗi, tôi không biết.",
            "Chúc bạn một ngày tốt lành!"
        ]
        return random.sample([f for f in static_fallbacks if f != target_vi], min(count, len(static_fallbacks)))

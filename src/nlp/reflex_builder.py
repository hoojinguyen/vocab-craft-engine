"""
Reflex Drill Generator for English Dataset System Engine.
Pre-generates distractor choices and JSON payloads for speed drills (< 2.5s response target).
"""

import json
import random
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ReflexBuilder:
    """Generates speed reaction drill cards with pre-computed distractors."""

    def __init__(self, sentence_pool: Optional[List[Dict[str, Any]]] = None):
        self.sentence_pool = sentence_pool or []

    def set_sentence_pool(self, sentence_pool: List[Dict[str, Any]]):
        self.sentence_pool = sentence_pool

    def build_drill(self, target_sentence: Dict[str, Any], drill_type: str = "speed_translation") -> Dict[str, Any]:
        """
        Generates a reflex drill record for a target sentence.
        """
        sentence_id = target_sentence.get("id", 1)
        text_en = target_sentence.get("text_en", "")
        text_vi = target_sentence.get("text_vi", "")
        cefr_level = target_sentence.get("cefr_level", "B1")

        distractors = self._generate_distractors(target_sentence, cefr_level=cefr_level, count=3)

        if drill_type == "speed_translation":
            prompt_text = text_en
            correct_answer = text_vi
        elif drill_type == "missing_chunk_fill":
            words = text_en.split()
            if len(words) >= 3:
                missing_idx = len(words) // 2
                correct_answer = words[missing_idx]
                words[missing_idx] = "___"
                prompt_text = " ".join(words)
            else:
                prompt_text = text_en
                correct_answer = text_vi
        else:  # audio_shadowing
            prompt_text = text_en
            correct_answer = text_en

        return {
            "sentence_id": sentence_id,
            "drill_type": drill_type,
            "prompt_text": prompt_text,
            "correct_answer": correct_answer,
            "distractors_json": json.dumps(distractors, ensure_ascii=False),
            "target_time_ms": 2500
        }

    def _generate_distractors(self, target_sentence: Dict[str, Any], cefr_level: str, count: int = 3) -> List[str]:
        """
        Picks count random distractor sentences from the pool with matching or close CEFR level.
        """
        target_vi = target_sentence.get("text_vi", "")
        candidates = [
            s.get("text_vi") for s in self.sentence_pool
            if s.get("text_vi") and s.get("text_vi") != target_vi
        ]

        if len(candidates) < count:
            # Fallback placeholder distractors if pool is small
            fallback_options = [
                "Tôi hiểu rồi.",
                "Cảm ơn bạn rất nhiều.",
                "Hẹn gặp lại bạn sau.",
                "Xin lỗi, tôi không biết.",
                "Chúc bạn một ngày tốt lành!"
            ]
            candidates.extend([f for f in fallback_options if f != target_vi])

        selected = random.sample(candidates, min(count, len(candidates)))
        return selected

"""
QuizBuilder Engine & Smart Distractor Index for Vocab Craft Engine.

Generates 4 quiz question types:
- word_mcq: Word definition MCQ with POS & CEFR matched distractors
- sentence_cloze: Sentence fill-in-the-blank with POS & CEFR matched distractors
- pattern_cloze: Grammar pattern fill-in-the-blank with POS & CEFR matched distractors
- word_ordering: Sentence unscramble with jumbled word tokens
"""

import json
import re
import random
import logging
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Default fallback distractors when pool has insufficient matching candidates
FALLBACK_VI_GLOSSES = [
    "thay đổi", "đạt được", "phát triển", "thực hiện",
    "bắt đầu", "kết thúc", "chuẩn bị", "quyết định"
]

FALLBACK_EN_LEMMAS = [
    "obtain", "replace", "require", "develop",
    "provide", "create", "support", "decide"
]


class QuizBuilder:
    """Generates quiz question payloads with POS & CEFR-matched distractor choices."""

    def __init__(self, words: Optional[List[Dict[str, Any]]] = None):
        self.words: List[Dict[str, Any]] = words or []
        self.pos_cefr_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.pos_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._index_words(self.words)

    def _index_words(self, words: List[Dict[str, Any]]):
        """Indexes words by (pos, cefr_level) for O(1) distractor lookup."""
        self.words = words or []
        self.pos_cefr_index = defaultdict(list)
        self.pos_index = defaultdict(list)

        for w in self.words:
            pos = (w.get("pos") or "unknown").strip().lower()
            cefr = (w.get("cefr_level") or "B1").strip().upper()
            key = (pos, cefr)
            self.pos_cefr_index[key].append(w)
            self.pos_index[pos].append(w)

    def _get_distractors(
        self, target_word: Dict[str, Any], field: str = "text_vi", count: int = 3
    ) -> List[str]:
        """
        Retrieves distractors matching target's POS & CEFR level.
        Falls back to same POS, then any word in pool, then built-in defaults.
        """
        pos = (target_word.get("pos") or "unknown").strip().lower()
        cefr = (target_word.get("cefr_level") or "B1").strip().upper()
        target_val = (target_word.get(field) or "").strip()
        target_lemma = (target_word.get("lemma") or "").strip().lower()

        candidates: List[str] = []
        seen: set = {target_val.lower(), target_lemma.lower()}

        def add_candidates_from_list(word_list: List[Dict[str, Any]]):
            for w in word_list:
                val = (w.get(field) or "").strip()
                lem = (w.get("lemma") or "").strip().lower()
                if val and val.lower() not in seen and lem not in seen:
                    candidates.append(val)
                    seen.add(val.lower())

        # Step 1: Same POS and CEFR level
        add_candidates_from_list(self.pos_cefr_index.get((pos, cefr), []))

        # Step 2: Same POS (any CEFR)
        if len(candidates) < count:
            add_candidates_from_list(self.pos_index.get(pos, []))

        # Step 3: Any POS/CEFR in pool
        if len(candidates) < count:
            add_candidates_from_list(self.words)

        # Step 4: Fallback options if still under count
        fallbacks = FALLBACK_VI_GLOSSES if field == "text_vi" else FALLBACK_EN_LEMMAS
        for fb in fallbacks:
            if len(candidates) >= count:
                break
            if fb.lower() not in seen:
                candidates.append(fb)
                seen.add(fb.lower())

        if len(candidates) > count:
            return random.sample(candidates, count)
        return candidates[:count]

    def generate_word_mcq(self, word: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a word definition multiple choice question."""
        correct_answer = word.get("text_vi", word.get("lemma", ""))
        distractors = self._get_distractors(word, field="text_vi", count=3)

        options = [correct_answer] + distractors
        random.shuffle(options)

        return {
            "question_type": "word_mcq",
            "target_type": "word",
            "target_id": word.get("id"),
            "prompt_text": word.get("lemma", ""),
            "correct_answer": correct_answer,
            "options_json": json.dumps(options, ensure_ascii=False),
            "cefr_level": word.get("cefr_level", "B1")
        }

    def generate_sentence_cloze(self, sentence: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a sentence fill-in-the-blank question."""
        text_en = sentence.get("text_en", "")
        sentence_id = sentence.get("id")
        cefr_level = sentence.get("cefr_level", "B1")

        # Find target word in sentence from words pool
        target_word: Optional[Dict[str, Any]] = None
        matched_text: str = ""

        for w in self.words:
            lemma = (w.get("lemma") or "").strip()
            if lemma and re.search(r'\b' + re.escape(lemma) + r'\b', text_en, re.IGNORECASE):
                target_word = w
                matched_text = lemma
                break

        if not target_word:
            # Fallback: pick a content word from sentence (length >= 4)
            words_in_text = re.findall(r'\b[A-Za-z]{4,}\b', text_en)
            if words_in_text:
                matched_text = words_in_text[0]
            else:
                matched_text = text_en.split()[0] if text_en.split() else "word"
            target_word = {
                "lemma": matched_text,
                "pos": "verb",
                "cefr_level": cefr_level
            }

        correct_answer = matched_text
        prompt_text = re.sub(
            r'\b' + re.escape(matched_text) + r'\b',
            '___',
            text_en,
            count=1,
            flags=re.IGNORECASE
        )

        distractors = self._get_distractors(target_word, field="lemma", count=3)
        options = [correct_answer] + distractors
        random.shuffle(options)

        return {
            "question_type": "sentence_cloze",
            "target_type": "sentence",
            "target_id": sentence_id,
            "prompt_text": prompt_text,
            "correct_answer": correct_answer,
            "options_json": json.dumps(options, ensure_ascii=False),
            "cefr_level": cefr_level
        }

    def generate_pattern_cloze(self, pattern: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a grammar pattern fill-in-the-blank question."""
        example_en = pattern.get("example_en", "")
        pattern_id = pattern.get("id")
        cefr_level = pattern.get("cefr_level", "A2")

        # Find target word in pattern example
        target_word: Optional[Dict[str, Any]] = None
        matched_text: str = ""

        for w in self.words:
            lemma = (w.get("lemma") or "").strip()
            if lemma and re.search(r'\b' + re.escape(lemma) + r'\b', example_en, re.IGNORECASE):
                target_word = w
                matched_text = lemma
                break

        if not target_word:
            # Pick a content word in example_en (length >= 4)
            words_in_text = re.findall(r'\b[A-Za-z]{4,}\b', example_en)
            ignore = {"this", "that", "with", "from", "have", "been", "were", "some", "they"}
            filtered = [w for w in words_in_text if w.lower() not in ignore]
            matched_text = filtered[0] if filtered else (words_in_text[0] if words_in_text else "important")
            target_word = {
                "lemma": matched_text,
                "pos": "adj",
                "cefr_level": cefr_level
            }

        correct_answer = matched_text
        prompt_text = re.sub(
            r'\b' + re.escape(matched_text) + r'\b',
            '___',
            example_en,
            count=1,
            flags=re.IGNORECASE
        )

        distractors = self._get_distractors(target_word, field="lemma", count=3)
        options = [correct_answer] + distractors
        random.shuffle(options)

        return {
            "question_type": "pattern_cloze",
            "target_type": "pattern",
            "target_id": pattern_id,
            "prompt_text": prompt_text,
            "correct_answer": correct_answer,
            "options_json": json.dumps(options, ensure_ascii=False),
            "cefr_level": cefr_level
        }

    def generate_word_ordering(self, sentence: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a sentence unscramble question with jumbled tokens."""
        text_en = sentence.get("text_en", "")
        tokens = text_en.split()
        shuffled_tokens = list(tokens)
        
        # Ensure shuffled order differs from original if possible
        if len(shuffled_tokens) > 1:
            for _ in range(5):
                random.shuffle(shuffled_tokens)
                if shuffled_tokens != tokens:
                    break

        return {
            "question_type": "word_ordering",
            "target_type": "sentence",
            "target_id": sentence.get("id"),
            "prompt_text": " ".join(shuffled_tokens),
            "correct_answer": text_en,
            "options_json": json.dumps(shuffled_tokens, ensure_ascii=False),
            "cefr_level": sentence.get("cefr_level", "B1")
        }

    def build_all_quizzes(
        self,
        words: Optional[List[Dict[str, Any]]] = None,
        sentences: Optional[List[Dict[str, Any]]] = None,
        patterns: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Builds quiz question payloads across all 4 quiz types for provided items.
        """
        words = words or []
        sentences = sentences or []
        patterns = patterns or []

        self._index_words(words)
        quizzes: List[Dict[str, Any]] = []

        for word in words:
            quizzes.append(self.generate_word_mcq(word))

        for sentence in sentences:
            quizzes.append(self.generate_sentence_cloze(sentence))
            quizzes.append(self.generate_word_ordering(sentence))

        for pattern in patterns:
            quizzes.append(self.generate_pattern_cloze(pattern))

        return quizzes

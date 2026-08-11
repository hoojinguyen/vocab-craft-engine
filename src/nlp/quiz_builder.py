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

# POS-aware fallback distractors when pool has insufficient matching candidates
FALLBACK_EN_LEMMAS_BY_POS = {
    "verb": ["obtain", "replace", "require", "develop", "provide", "create", "support", "decide"],
    "noun": ["option", "result", "system", "method", "process", "detail", "element", "feature"],
    "adj": ["important", "difficult", "possible", "similar", "general", "certain", "current", "available"],
    "adv": ["quickly", "clearly", "easily", "finally", "usually", "directly", "recently", "simply"],
}

FALLBACK_VI_GLOSSES_BY_POS = {
    "verb": ["thay đổi", "đạt được", "phát triển", "thực hiện", "bắt đầu", "kết thúc", "chuẩn bị", "quyết định"],
    "noun": ["lựa chọn", "kết quả", "hệ thống", "phương pháp", "quá trình", "chi tiết", "yếu tố", "tính năng"],
    "adj": ["quan trọng", "khó khăn", "có thể", "tương tự", "chung", "nhất định", "hiện tại", "sẵn có"],
    "adv": ["nhanh chóng", "rõ ràng", "dễ dàng", "cuối cùng", "thường", "trực tiếp", "gần đây", "đơn giản"],
}


class QuizBuilder:
    """Generates quiz question payloads with POS & CEFR-matched distractor choices."""

    def __init__(self, words: Optional[List[Dict[str, Any]]] = None):
        self.words: List[Dict[str, Any]] = words or []
        self.pos_cefr_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.pos_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._index_words(self.words)

    def _index_words(self, words: List[Dict[str, Any]]):
        """Indexes words by (pos, cefr_level) and lemma for O(1) distractor and token lookup."""
        self.words = words or []
        self.pos_cefr_index = defaultdict(list)
        self.pos_index = defaultdict(list)
        self.lemma_dict = {w["lemma"].lower(): w for w in self.words if w.get("lemma")}

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
        Retrieves distractors tier-by-tier matching target's POS & CEFR level.
        - Tier 1: Same POS + Same CEFR level
        - Tier 2: Same POS (different CEFR level)
        - Tier 3: Any word in pool (fast random sampling)
        - Tier 4: POS-aware fallback dictionary
        Tracks both gloss and lemma in `seen` set to avoid duplicate lemmas or glosses.
        """
        pos = (target_word.get("pos") or "unknown").strip().lower()
        cefr = (target_word.get("cefr_level") or "B1").strip().upper()
        target_val = (target_word.get(field) or "").strip()
        target_lemma = (target_word.get("lemma") or "").strip().lower()

        selected: List[str] = []
        seen: set = set()

        if target_val:
            seen.add(target_val.lower())
        if target_lemma:
            seen.add(target_lemma.lower())

        def filter_and_sample(word_list: List[Dict[str, Any]], needed: int) -> List[str]:
            candidates: List[str] = []
            for w in word_list:
                val = (w.get(field) or "").strip()
                lem = (w.get("lemma") or "").strip().lower()
                if val and val.lower() not in seen and lem not in seen:
                    candidates.append(val)

            unique_candidates: List[str] = []
            temp_seen: set = set()
            for val in candidates:
                if val.lower() not in temp_seen:
                    unique_candidates.append(val)
                    temp_seen.add(val.lower())

            sampled = random.sample(unique_candidates, min(needed, len(unique_candidates)))
            for s in sampled:
                for w in word_list:
                    if (w.get(field) or "").strip().lower() == s.lower():
                        lem = (w.get("lemma") or "").strip().lower()
                        if lem:
                            seen.add(lem)
                        break
                seen.add(s.lower())
            return sampled

        # Tier 1: Same POS and Same CEFR level
        tier1_words = self.pos_cefr_index.get((pos, cefr), [])
        if tier1_words and len(selected) < count:
            selected.extend(filter_and_sample(tier1_words, count - len(selected)))

        # Tier 2: Same POS (different CEFR level)
        if len(selected) < count:
            tier2_words = self.pos_index.get(pos, [])
            selected.extend(filter_and_sample(tier2_words, count - len(selected)))

        # Tier 3: Any word in pool (fast random sampling)
        if len(selected) < count and self.words:
            needed = count - len(selected)
            sample_size = min(len(self.words), max(needed * 10, 50))
            for w in random.sample(self.words, sample_size):
                val = (w.get(field) or "").strip()
                lem = (w.get("lemma") or "").strip().lower()
                if val and val.lower() not in seen and (not lem or lem not in seen):
                    selected.append(val)
                    seen.add(val.lower())
                    if lem:
                        seen.add(lem)
                    if len(selected) == count:
                        break

        # Tier 4: POS-aware fallback dictionary
        if len(selected) < count:
            fallbacks_dict = FALLBACK_VI_GLOSSES_BY_POS if field == "text_vi" else FALLBACK_EN_LEMMAS_BY_POS
            fallback_list = fallbacks_dict.get(pos, fallbacks_dict.get("verb", []))

            fb_candidates = [fb for fb in fallback_list if fb.lower() not in seen]
            needed = count - len(selected)
            sampled_fb = random.sample(fb_candidates, min(needed, len(fb_candidates)))
            for fb in sampled_fb:
                selected.append(fb)
                seen.add(fb.lower())

        return selected[:count]

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

        tokens = re.findall(r'\b[A-Za-z]+\b', text_en)
        for token in tokens:
            token_lower = token.lower()
            if token_lower in self.lemma_dict:
                target_word = self.lemma_dict[token_lower]
                matched_text = target_word.get("lemma", token)
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

        tokens = re.findall(r'\b[A-Za-z]+\b', example_en)
        for token in tokens:
            token_lower = token.lower()
            if token_lower in self.lemma_dict:
                target_word = self.lemma_dict[token_lower]
                matched_text = target_word.get("lemma", token)
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

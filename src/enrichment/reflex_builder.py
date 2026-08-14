"""Reflex Drill Exercise Generator with CEFR-graded Dynamic Distractors."""

import json
import logging
import random
import re
from typing import Any

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TARGET_DRILL_TIME_MS = 2500


class ReflexBuilder:
    def __init__(self, *, seed: int = 0, batch_size: int = 1_000):
        self._seed = seed
        self._batch_size = batch_size

    def build(self, db_mgr: DuckDBManager, max_drills_per_type: int = 50000) -> int:
        if max_drills_per_type < 0:
            raise ValueError("max_drills_per_type must be nonnegative")
        if self._batch_size <= 0:
            raise ValueError("batch_size must be positive")

        conn = db_mgr.get_connection()
        conn.execute("DELETE FROM reflex_drills")
        sentences = conn.execute("""
            SELECT id, text_en, text_vi, cefr_level 
            FROM sentences 
            WHERE text_en IS NOT NULL AND text_vi IS NOT NULL
            ORDER BY id
        """).fetchall()

        if not sentences:
            logger.warning("No sentences found in staging DB to generate reflex drills")
            return 0

        # Collect translation pools grouped by CEFR (or general pool)
        all_vi_texts = [
            row[2].strip() for row in sentences if row[2] and row[2].strip()
        ]
        if len(all_vi_texts) < 4:
            # Fallback default distractors if pool is too small
            all_vi_texts.extend(
                [
                    "Tôi thích đi du lịch.",
                    "Hôm nay thời tiết rất đẹp.",
                    "Bạn có thể giúp tôi không?",
                    "Hẹn gặp lại bạn vào ngày mai.",
                ]
            )

        # Collect word pool for cloze distractors
        words = conn.execute("""
            SELECT lemma
            FROM words
            WHERE length(lemma) >= 3
            ORDER BY lower(lemma), id
            """).fetchall()
        word_pool = [row[0].strip().lower() for row in words if row[0]]
        if len(word_pool) < 10:
            word_pool.extend(
                [
                    "water",
                    "house",
                    "school",
                    "music",
                    "friend",
                    "family",
                    "country",
                    "story",
                ]
            )

        drills_batch: list[dict[str, Any]] = []
        rng = random.Random(self._seed)
        speed_translation_created = 0
        cloze_created = 0

        for sid, text_en, text_vi, cefr in sentences:
            en_clean = text_en.strip()
            vi_clean = text_vi.strip()
            if not en_clean or not vi_clean:
                continue

            # Drill 1: Speed Translation (EN -> VI prompt with 3 random VI distractors)
            if speed_translation_created < max_drills_per_type:
                candidates_vi = [t for t in all_vi_texts if t != vi_clean]
                distractors_vi = (
                    rng.sample(candidates_vi, min(3, len(candidates_vi)))
                    if len(candidates_vi) >= 3
                    else candidates_vi[:3]
                )

                drills_batch.append(
                    {
                        "sentence_id": sid,
                        "drill_type": "speed_translation",
                        "prompt_text": en_clean,
                        "correct_answer": vi_clean,
                        "distractors_json": json.dumps(
                            distractors_vi, ensure_ascii=False
                        ),
                        "target_time_ms": TARGET_DRILL_TIME_MS,
                    }
                )
                speed_translation_created += 1

            # Drill 2: Cloze / Missing Word Fill
            words_in_sent = re.findall(r"\b[a-zA-Z]{3,}\b", en_clean)
            if words_in_sent and cloze_created < max_drills_per_type:
                target_word = rng.choice(words_in_sent)
                masked_prompt = re.sub(
                    r"\b" + re.escape(target_word) + r"\b", "_______", en_clean, count=1
                )

                target_lower = target_word.lower()
                cand_words = [
                    w
                    for w in word_pool
                    if w != target_lower and abs(len(w) - len(target_lower)) <= 2
                ]
                if len(cand_words) < 3:
                    cand_words = [w for w in word_pool if w != target_lower]

                distractors_cloze = (
                    rng.sample(cand_words, min(3, len(cand_words)))
                    if len(cand_words) >= 3
                    else cand_words[:3]
                )

                drills_batch.append(
                    {
                        "sentence_id": sid,
                        "drill_type": "cloze",
                        "prompt_text": f"Fill in the blank: {masked_prompt}",
                        "correct_answer": target_word,
                        "distractors_json": json.dumps(
                            distractors_cloze, ensure_ascii=False
                        ),
                        "target_time_ms": TARGET_DRILL_TIME_MS,
                    }
                )
                cloze_created += 1

            if len(drills_batch) >= self._batch_size:
                db_mgr.insert_batch_fast("reflex_drills", drills_batch)
                drills_batch.clear()

        if drills_batch:
            db_mgr.insert_batch_fast("reflex_drills", drills_batch)

        created = speed_translation_created + cloze_created
        logger.info("Generated and saved %d reflex drill cards", created)
        return created

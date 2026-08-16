"""Reflex Drill Exercise Generator with CEFR-graded Dynamic Distractors."""

import json
import logging
import random
import re
import time
from collections.abc import Iterable, Sequence
from typing import Any

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TARGET_DRILL_TIME_MS = 2500


def _dedupe_stable(values: Iterable[str]) -> list[str]:
    """Return non-empty values once, preserving their first-seen spelling."""
    result = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _select_distractors(
    candidates: list[str], answer: str, rng: random.Random
) -> list[str] | None:
    """Select three distinct candidates that do not collide with the answer."""
    if len(candidates) < 3:
        return None
    distractors = rng.sample(candidates, 3)
    answer_key = answer.casefold()
    if len({value.casefold() for value in distractors}) != 3 or answer_key in {
        value.casefold() for value in distractors
    }:
        return None
    return distractors


def _select_indexed_distractors(
    pool: Sequence[str], answer_index: int | None, rng: random.Random
) -> list[str] | None:
    """Select three values by index while excluding the answer's pool index."""
    if answer_index is None or len(pool) < 4:
        return None
    if not 0 <= answer_index < len(pool):
        return None

    selected_indices = rng.sample(range(len(pool) - 1), 3)
    return [
        pool[index if index < answer_index else index + 1] for index in selected_indices
    ]


def _build_cloze_candidates(
    target_lower: str,
    words_by_length: dict[int, list[str]],
    word_pool: list[str],
) -> list[str]:
    """Build candidates for one selected target from bounded buckets."""
    bucket_candidates = [
        word
        for length in range(len(target_lower) - 2, len(target_lower) + 3)
        for word in words_by_length.get(length, [])
        if word.casefold() != target_lower
    ]
    if len(bucket_candidates) >= 3:
        return bucket_candidates
    return [word for word in word_pool if word.casefold() != target_lower]


class ReflexBuilder:
    def __init__(self, *, seed: int = 0, batch_size: int = 1_000):
        self._seed = seed
        self._batch_size = batch_size

    def build(self, db_mgr: DuckDBManager, max_drills_per_type: int = 50000) -> int:
        if max_drills_per_type < 0:
            raise ValueError("max_drills_per_type must be nonnegative")
        if self._batch_size <= 0:
            raise ValueError("batch_size must be positive")
        started_at = time.monotonic()

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
        all_vi_texts = _dedupe_stable(row[2] for row in sentences if row[2])
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
            all_vi_texts = _dedupe_stable(all_vi_texts)

        vi_index_by_answer = {
            answer.casefold(): index for index, answer in enumerate(all_vi_texts)
        }

        # Collect word pool for cloze distractors
        words = conn.execute("""
            SELECT lemma
            FROM words
            WHERE length(lemma) >= 3
            ORDER BY lower(lemma), id
            """).fetchall()
        word_pool = _dedupe_stable(row[0].lower() for row in words if row[0])
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
            word_pool = _dedupe_stable(word_pool)
        words_by_length: dict[int, list[str]] = {}
        for word in word_pool:
            words_by_length.setdefault(len(word), []).append(word)
        pending_by_type: dict[str, list[dict[str, Any]]] = {
            "speed_translation": [],
            "cloze": [],
        }
        rng = random.Random(self._seed)
        speed_translation_created = 0
        cloze_created = 0
        speed_translation_skipped = 0
        cloze_skipped = 0
        sentences_examined = 0

        def flush(drill_type: str) -> None:
            pending = pending_by_type[drill_type]
            if not pending:
                return
            try:
                db_mgr.insert_batch_fast("reflex_drills", pending)
            except Exception as exc:
                raise RuntimeError(
                    f"reflex batch insert failed for {drill_type}"
                ) from exc
            pending.clear()
            created = (
                speed_translation_created
                if drill_type == "speed_translation"
                else cloze_created
            )
            elapsed = time.monotonic() - started_at
            logger.info(
                "reflex progress type=%s sentences_examined=%d created=%d/%d "
                "elapsed=%.3fs",
                drill_type,
                sentences_examined,
                created,
                max_drills_per_type,
                elapsed,
            )

        for sid, text_en, text_vi, cefr in sentences:
            sentences_examined += 1
            en_clean = text_en.strip()
            vi_clean = text_vi.strip()
            if not en_clean or not vi_clean:
                continue

            # Drill 1: Speed Translation (EN -> VI prompt with 3 random VI distractors)
            if speed_translation_created < max_drills_per_type:
                distractors_vi = _select_indexed_distractors(
                    all_vi_texts,
                    vi_index_by_answer.get(vi_clean.casefold()),
                    rng,
                )
                if distractors_vi is not None:
                    pending_by_type["speed_translation"].append(
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
                    if len(pending_by_type["speed_translation"]) >= self._batch_size:
                        flush("speed_translation")
                else:
                    speed_translation_skipped += 1

            # Drill 2: Cloze / Missing Word Fill
            words_in_sent = re.findall(r"\b[a-zA-Z]{3,}\b", en_clean)
            if words_in_sent and cloze_created < max_drills_per_type:
                target_word = rng.choice(words_in_sent)
                masked_prompt = re.sub(
                    r"\b" + re.escape(target_word) + r"\b", "_______", en_clean, count=1
                )

                distractors_cloze = _select_distractors(
                    _build_cloze_candidates(
                        target_word.lower(), words_by_length, word_pool
                    ),
                    target_word,
                    rng,
                )
                if distractors_cloze is not None:
                    pending_by_type["cloze"].append(
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
                    if len(pending_by_type["cloze"]) >= self._batch_size:
                        flush("cloze")
                else:
                    cloze_skipped += 1
            elif cloze_created < max_drills_per_type:
                cloze_skipped += 1

        flush("speed_translation")
        flush("cloze")

        created = speed_translation_created + cloze_created
        logger.info(
            "Completed reflex build: speed_translation created=%d/%d skipped=%d; "
            "cloze created=%d/%d skipped=%d; sentences_examined=%d elapsed=%.3fs",
            speed_translation_created,
            max_drills_per_type,
            speed_translation_skipped,
            cloze_created,
            max_drills_per_type,
            cloze_skipped,
            sentences_examined,
            time.monotonic() - started_at,
        )
        return created

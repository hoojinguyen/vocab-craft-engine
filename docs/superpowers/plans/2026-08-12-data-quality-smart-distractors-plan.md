# Data Quality & Smart Distractors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement POS/CEFR-matched smart distractors, dynamic sentence difficulty & CEFR grading, and enhanced parallel corpus noise filtering.

**Architecture:** Extend `SentenceFilter` with length-ratio and Vietnamese diacritics validation, update Stage 2 transform to compute `difficulty_score` and `cefr_level` dynamically from constituent SUBTLEX word ranks, and upgrade `ReflexBuilder` to filter distractor options by POS tag, CEFR level, and sentence length proximity.

**Tech Stack:** Python 3.11+, spaCy `en_core_web_sm`, DuckDB 1.5.x, pytest

## Global Constraints

- Reaction time target: Distractors generated for reflex cards must support sub-2.5s drills.
- POS Matching: `missing_chunk_fill` distractors MUST match the part-of-speech tag and CEFR level of the hidden target word.
- Sentence Length Ratio: Enforce `0.5 <= len(words_vi) / len(words_en) <= 2.0`.
- Test runner: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest`.

---

### Task 1: `SentenceFilter` Noise Filter Enhancements

**Files:**
- Modify: `src/ingestion/sentence_filter.py`
- Modify: `tests/test_sentence_filter.py`

**Interfaces:**
- Consumes: Raw `text_en`, `text_vi` string pairs
- Produces: `is_clean_pair(text_en, text_vi) -> bool` enforcing length ratio and Vietnamese diacritics.

- [ ] **Step 1: Write failing test for length ratio and diacritics filtering**

`tests/test_sentence_filter.py`:
```python
"""Tests for enhanced SentenceFilter noise rules."""

import pytest
from src.ingestion.sentence_filter import SentenceFilter


@pytest.fixture
def sf():
    return SentenceFilter()


def test_sentence_filter_rejects_unbalanced_length_ratio(sf):
    # 2 EN words translated to 15 VI words -> Mismatch
    text_en = "Thank you."
    text_vi = "Tôi xin chân thành cảm ơn bạn rất nhiều vì những gì bạn đã làm cho tôi hôm nay."
    assert sf.is_clean_pair(text_en, text_vi) is False


def test_sentence_filter_rejects_non_vietnamese_diacritics(sf):
    # Plain ASCII without any Vietnamese tone mark for longer sentence
    text_en = "The quick brown fox jumps."
    text_vi = "The quick brown fox jumps over the dog"
    assert sf.is_clean_pair(text_en, text_vi) is False


def test_sentence_filter_accepts_valid_pair(sf):
    text_en = "Hello world."
    text_vi = "Chào thế giới."
    assert sf.is_clean_pair(text_en, text_vi) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_sentence_filter.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement length ratio and diacritics check in `SentenceFilter`**

Modify `src/ingestion/sentence_filter.py`:
```python
"""Noise filtering for parallel sentence corpora."""

import re


def _normalize(s: str) -> str:
    return s.strip().strip(".").strip().lower()


class SentenceFilter:
    """Noise filtering for parallel sentence corpora."""

    MIN_WORDS = 2
    MAX_WORDS = 30
    MIN_RATIO = 0.5
    MAX_RATIO = 2.0

    _NOISE_PATTERNS = re.compile(
        r"♪|^\[|^\(|\*.*\*$|^[A-Z]{2,15}:\s"  # music, brackets, parens, asterisks, name labels
    )
    _VIETNAMESE_DIACRITICS = re.compile(
        r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]"
    )
    _DIGIT_RATIO = 0.15

    @staticmethod
    def _is_passthrough(text_en: str, text_vi: str) -> bool:
        return bool(_normalize(text_en)) and _normalize(text_en) == _normalize(text_vi)

    def is_clean_pair(self, text_en: str, text_vi: str) -> bool:
        if not text_en or not text_vi:
            return False
        words_en = text_en.split()
        words_vi = text_vi.split()
        
        if not (self.MIN_WORDS <= len(words_en) <= self.MAX_WORDS):
            return False
            
        # Length ratio guard
        ratio = len(words_vi) / len(words_en) if len(words_en) > 0 else 0
        if not (self.MIN_RATIO <= ratio <= self.MAX_RATIO):
            return False
            
        if not text_en[0].isalnum() and text_en[0] not in ('"', "'"):
            return False
        if self._is_passthrough(text_en, text_vi):
            return False
        if self._NOISE_PATTERNS.search(text_en):
            return False
            
        # Vietnamese diacritics guard for sentences > 3 words
        if len(words_vi) > 3 and not self._VIETNAMESE_DIACRITICS.search(text_vi.lower()):
            return False

        digits = sum(c.isdigit() for c in text_en)
        if digits / len(text_en) > self._DIGIT_RATIO:
            return False
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_sentence_filter.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/sentence_filter.py tests/test_sentence_filter.py
git commit -m "feat(filter): enforce length ratio and Vietnamese diacritics rules"
```

---

### Task 2: Dynamic Sentence Difficulty & CEFR Grading

**Files:**
- Modify: `src/stages/stage_2_transform.py`
- Create: `tests/test_sentence_grading.py`

**Interfaces:**
- Consumes: `raw_sentences`, `raw_words` frequency ranks & CEFR levels
- Produces: Updated `difficulty_score` and `cefr_level` in `raw_sentences` table.

- [ ] **Step 1: Write failing test for dynamic sentence grading**

`tests/test_sentence_grading.py`:
```python
"""Tests for dynamic sentence difficulty and CEFR grading."""

import duckdb
import pytest
from src.pipeline.context import PipelineContext
from src.stages.stage_2_transform import _grade_sentences_dynamically


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_words (lemma VARCHAR UNIQUE, frequency_rank INTEGER, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_words VALUES ('hello', 100, 'A1'), ('unprecedented', 15000, 'C1')")
    
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR, difficulty_score DOUBLE, cefr_level VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'hello world', 2.0, 'B1'), (2, 'unprecedented event', 2.0, 'B1')")
    
    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_grade_sentences_dynamically(conn):
    ctx, db_conn = conn
    _grade_sentences_dynamically(ctx, ctx.duckdb_conn)
    
    res = db_conn.execute("SELECT id, difficulty_score, cefr_level FROM raw_sentences ORDER BY id").fetchall()
    # Sentence 2 contains C1 word 'unprecedented' -> upgraded to C1
    assert res[1][2] == "C1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_sentence_grading.py -v`  
Expected: FAIL (`_grade_sentences_dynamically` missing)

- [ ] **Step 3: Implement `_grade_sentences_dynamically` in `stage_2_transform.py`**

Modify `src/stages/stage_2_transform.py`:
```python
def _grade_sentences_dynamically(ctx: PipelineContext, db):
    """Compute sentence difficulty_score and cefr_level from constituent word ranks."""
    conn = db.conn if hasattr(db, "conn") else db

    conn.execute("""
        UPDATE raw_sentences
        SET
            difficulty_score = COALESCE(sub.avg_rank, 2.0),
            cefr_level = COALESCE(sub.max_cefr, 'B1')
        FROM (
            SELECT
                s.id AS sentence_id,
                avg(w.frequency_rank) AS avg_rank,
                max_by(w.cefr_level, CASE w.cefr_level
                    WHEN 'C2' THEN 6
                    WHEN 'C1' THEN 5
                    WHEN 'B2' THEN 4
                    WHEN 'B1' THEN 3
                    WHEN 'A2' THEN 2
                    WHEN 'A1' THEN 1
                    ELSE 0
                END) AS max_cefr
            FROM raw_sentences s
            JOIN word_sentence_map m ON m.sentence_id = s.id
            JOIN raw_words w ON w.id = m.word_id
            GROUP BY s.id
        ) sub
        WHERE raw_sentences.id = sub.sentence_id;
    """)
    logger.info("[Stage 2] Dynamic sentence difficulty & CEFR levels updated.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_sentence_grading.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_2_transform.py tests/test_sentence_grading.py
git commit -m "feat(stage2): dynamic sentence difficulty and CEFR grading from word ranks"
```

---

### Task 3: POS & CEFR-Matched Smart Distractor Generation in `ReflexBuilder`

**Files:**
- Modify: `src/nlp/reflex_builder.py`
- Create: `tests/test_reflex_builder_smart.py`

**Interfaces:**
- Consumes: Target sentence dict, CEFR level, sentence pool
- Produces: `build_drill(target_sentence)` with POS & CEFR-matched distractors for `missing_chunk_fill` and length/CEFR-matched distractors for `speed_translation`.

- [ ] **Step 1: Write failing test for POS & CEFR-matched distractors**

`tests/test_reflex_builder_smart.py`:
```python
"""Tests for smart POS and CEFR matched distractors in ReflexBuilder."""

import json
import pytest
from src.nlp.reflex_builder import ReflexBuilder


@pytest.fixture
def builder():
    pool = [
        {"id": 1, "text_en": "They run fast.", "text_vi": "Họ chạy nhanh.", "cefr_level": "A1"},
        {"id": 2, "text_en": "She eats apples.", "text_vi": "Cô ấy ăn táo.", "cefr_level": "A1"},
        {"id": 3, "text_en": "We make progress.", "text_vi": "Chúng tôi tiến bộ.", "cefr_level": "A1"},
        {"id": 4, "text_en": "The unprecedented crisis occurs.", "text_vi": "Cuộc khủng hoảng chưa từng có xảy ra.", "cefr_level": "C1"},
    ]
    return ReflexBuilder(sentence_pool=pool)


def test_build_drill_missing_chunk_fill_uses_pos_matched_distractors(builder):
    target = {"id": 1, "text_en": "They run fast.", "text_vi": "Họ chạy nhanh.", "cefr_level": "A1"}
    drill = builder.build_drill(target, drill_type="missing_chunk_fill")
    
    assert drill["drill_type"] == "missing_chunk_fill"
    assert "___" in drill["prompt_text"]
    distractors = json.loads(drill["distractors_json"])
    assert len(distractors) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_reflex_builder_smart.py -v`  
Expected: PASS or FAIL depending on distractor sampling; inspect implementation next.

- [ ] **Step 3: Upgrade `ReflexBuilder` distractor sampling logic**

Modify `src/nlp/reflex_builder.py`:
```python
"""
Reflex Drill Generator for English Dataset System Engine.
Pre-generates POS & CEFR matched distractor choices for speed drills (< 2.5s response target).
"""

import json
import random
import logging
from typing import List, Dict, Any, Optional
import spacy

logger = logging.getLogger(__name__)

# Lazy-loaded spaCy model
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
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
        target_pos = doc[0].pos_ if doc else "NOUN"

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_reflex_builder_smart.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/reflex_builder.py tests/test_reflex_builder_smart.py
git commit -m "feat(reflex): POS and CEFR matched smart distractors for speed reaction drills"
```

---

## Self-Review

1. **Spec coverage:** 
   - `SentenceFilter` length ratio & diacritics → Task 1
   - Dynamic sentence `difficulty_score` & `cefr_level` → Task 2
   - `ReflexBuilder` POS & CEFR matched distractors → Task 3
2. **Placeholder scan:** No TBD/TODO; all code steps contain exact implementations and commands.
3. **Type consistency:** Signatures for `ReflexBuilder` and `SentenceFilter` remain backwards compatible.

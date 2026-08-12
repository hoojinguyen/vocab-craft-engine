# Data Quality & Smart Distractors Design Spec

> **Date:** 2026-08-12  
> **Status:** APPROVED BY USER  
> **Goal:** Enhance reflex drill quality with POS/CEFR-matched smart distractors, calculate dynamic sentence difficulty & CEFR levels, and enforce strict parallel sentence noise filtering.

---

## 1. Overview & Objectives

This design improves linguistic precision and drill automaticity (< 2.5s target reaction time) by:
1. **POS & CEFR-Matched Smart Distractors:** Replacing random sampling in `ReflexBuilder` with grammatical part-of-speech traps and length/CEFR-aligned candidates.
2. **Dynamic Sentence Grading:** Computing exact sentence `difficulty_score` from SUBTLEX constituent word ranks and assigning sentence `cefr_level` based on peak token rarity.
3. **Strict Noise Filtering:** Enhancing `SentenceFilter` with length ratio bounds and Vietnamese diacritics validation to purge garbled machine translations.

---

## 2. Component Design Details

### 2.1 Smart Distractor Generation (`src/nlp/reflex_builder.py`)
- **Fill-in-the-Blank (`missing_chunk_fill`):**
  - Extract part-of-speech (POS) tag for the omitted target word using spaCy.
  - Query distractor candidates matching the SAME POS tag and SAME CEFR level as the target word.
- **Speed Translation (`speed_translation`):**
  - Filter candidate sentences from `vi_pool` matching target `cefr_level` and character/word length within ±25%.

### 2.2 Dynamic Sentence Grading (`src/stages/stage_2_transform.py`)
- **`difficulty_score`:**
  - SQL/Vectorized calculation: Average SUBTLEX frequency rank across non-stopword tokens in the sentence.
- **`cefr_level`:**
  - Rated as the highest CEFR level present among the non-stopword tokens in the sentence (A1 < A2 < B1 < B2 < C1 < C2).

### 2.3 Noise Filtering & Quality Gates (`src/ingestion/sentence_filter.py`)
- **Length Ratio Guard:** Enforce `0.5 <= len(words_vi) / len(words_en) <= 2.0`.
- **Vietnamese Diacritics Guard:** Enforce presence of valid Vietnamese Unicode tone marks/diacritics in `text_vi` to reject untranslated English or ASCII garbage.

---

## 3. Verification Plan

### Automated Tests
1. **Reflex Builder Unit Tests:** Verify `missing_chunk_fill` distractors match POS tag & CEFR level; verify `speed_translation` distractors match length & CEFR level.
2. **Sentence Filter Unit Tests:** Test length ratio edge cases and Vietnamese diacritics validation.
3. **Sentence Grading Integration Tests:** Verify `difficulty_score` and `cefr_level` populated correctly in staging DB.

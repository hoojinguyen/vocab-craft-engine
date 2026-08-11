# Design Spec: Interactive Quiz & Distractor Generator Engine

**Date:** 2026-08-11  
**Status:** Approved  
**Module:** `src/nlp/quiz_builder.py`, `src/db/staging_db.py`, `main.py`, `src/export/sqlite_exporter.py`  

---

## 1. Executive Summary & Goals

The Interactive Quiz & Distractor Generator Engine (`QuizBuilder`) automatically generates pedagogically sound, multi-target practice quizzes (`quiz_questions`) for vocabulary words, phrases, sentence patterns, and full sentences. It features a Smart Distractor Index that filters distractor choices by Part-of-Speech (POS) and CEFR level (e.g. A2 verb distractors for an A2 verb target), eliminating obviously incorrect or mismatched options. It packages questions into mobile SQLite with 1-byte Integer ENUMs, a `v_quiz_questions` SQL View, and sub-1.0ms fetch SLA.

---

## 2. Architecture & Quiz Generator Design

### 2.1 Quiz Builder (`src/nlp/quiz_builder.py`)
Class `QuizBuilder` maintains an in-memory `pos_cefr_index: Dict[Tuple[str, str], List[Dict[str, Any]]]` mapping `(pos, cefr_level)` pairs to word candidates for fast O(1) distractor selection.

#### 4 Supported Question Types:
1. **`word_mcq` (MCQ Word Definition):**
   - **Target Type:** `'word'`
   - **Prompt:** Target English lemma (e.g., `"abandon"`)
   - **Correct Answer:** Vietnamese gloss (e.g., `"rời bỏ, từ bỏ"`)
   - **Options:** Array of 4 Vietnamese glosses (1 correct + 3 distractors with same POS & CEFR level)
2. **`sentence_cloze` (Sentence Fill-in-blank):**
   - **Target Type:** `'sentence'`
   - **Prompt:** English sentence with target word replaced by `___` (e.g., `"She decided to ___ her old car."`)
   - **Correct Answer:** Target English word (e.g., `"abandon"`)
   - **Options:** Array of 4 English words (1 correct + 3 distractors with same POS & CEFR level)
3. **`pattern_cloze` (Grammar Pattern Fill-in-blank):**
   - **Target Type:** `'pattern'`
   - **Prompt:** Sentence pattern example with key structural word replaced by `___` (e.g., `"It is ___ to learn a new language."`)
   - **Correct Answer:** Target structural word (e.g., `"important"`)
   - **Options:** Array of 4 words of matching POS/CEFR level
4. **`word_ordering` (Sentence Unscramble):**
   - **Target Type:** `'sentence'`
   - **Prompt:** Jumbled string of tokens
   - **Correct Answer:** Correct full English sentence string
   - **Options:** Array of shuffled tokens `["to", "important", "It", "learn", "language", "is", "a", "new"]`

---

## 3. Database & Pipeline Integration

### 3.1 Staging DB Schema (`src/db/staging_db.py`)
Table `quiz_questions`:
```sql
CREATE TABLE IF NOT EXISTS quiz_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    prompt_text TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    options_json TEXT NOT NULL,
    cefr_level TEXT NOT NULL DEFAULT 'B1'
);

CREATE INDEX IF NOT EXISTS idx_quiz_type_cefr ON quiz_questions(question_type, cefr_level);
CREATE INDEX IF NOT EXISTS idx_quiz_target ON quiz_questions(target_type, target_id);
```
Batch Helper: `insert_quiz_questions_batch(self, questions: List[Dict[str, Any]]) -> int`.

### 3.2 Pipeline Step (`main.py`)
Function `run_quiz_step(db_mgr: DatabaseManager) -> int`:
1. Instantiates `QuizBuilder`.
2. Fetches words, sentences, and sentence patterns from staging database.
3. Pre-indexes words by `(pos, cefr_level)`.
4. Generates quiz questions across all 4 quiz types.
5. Inserts quiz questions via `insert_quiz_questions_batch()`.
6. Connected to Step 4E of `run_pipeline()`.

### 3.3 Mobile Exporter (`src/export/sqlite_exporter.py`)
- Maps `question_type` (`1: word_mcq`, `2: sentence_cloze`, `3: pattern_cloze`, `4: word_ordering`) and `target_type` (`1: word`, `2: phrase`, `3: pattern`, `4: sentence`) to `TINYINT`.
- Creates SQL View `v_quiz_questions`:
```sql
CREATE VIEW IF NOT EXISTS v_quiz_questions AS
SELECT 
    q.id AS quiz_id,
    q.question_type,
    q.target_type,
    q.target_id,
    q.prompt_text,
    q.correct_answer,
    q.options_json,
    q.cefr_level,
    s.audio_path
FROM quiz_questions q
LEFT JOIN sentences s ON q.target_type = 4 AND q.target_id = s.id;
```
- Adds covering index `idx_quiz_cov ON quiz_questions(question_type, cefr_level, id, prompt_text)` and benchmark `quiz_fetch_ms` (< 1.0 ms SLA).

---

## 4. Testing & Verification Plan

1. **Unit Tests (`tests/test_quiz_builder.py`):**
   - Verify `QuizBuilder` generates 4 quiz types with valid JSON options format.
   - Assert distractors match target POS and CEFR level.
2. **Integration Tests (`tests/test_quiz_pipeline.py`):**
   - Verify `run_quiz_step()` end-to-end population of `quiz_questions` table.
3. **Mobile Exporter Tests (`tests/test_sqlite_exporter.py`):**
   - Verify Integer ENUM encoding for `question_type` and `target_type`.
   - Verify `v_quiz_questions` View output and assert `quiz_fetch_ms` < 1.0 ms.

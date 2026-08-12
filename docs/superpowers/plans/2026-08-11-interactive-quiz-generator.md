# Interactive Quiz & Distractor Generator Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated Interactive Quiz & Distractor Generator Engine (`QuizBuilder`) that pre-computes 4 types of practice drills (`word_mcq`, `sentence_cloze`, `pattern_cloze`, `word_ordering`) with POS and CEFR-matched smart distractors, stores questions into `quiz_questions`, and packages a mobile SQL View `v_quiz_questions` with sub-1.0ms fetch SLA.

**Architecture:** Create `QuizBuilder` in `src/nlp/quiz_builder.py` with `pos_cefr_index` for O(1) distractor selection. Add `quiz_questions` schema and `insert_quiz_questions_batch` helper to `DatabaseManager` in `src/db/staging_db.py`. Add `run_quiz_step` into Step 4E of `main.py`. Update `SQLiteExporter` to encode `question_type` and `target_type` as Integer ENUMs, create `v_quiz_questions` SQL View, and benchmark `quiz_fetch_ms` (< 1.0 ms SLA).

**Tech Stack:** Python 3.10+, SQLite 3, pytest.

## Global Constraints

- **Quiz Types (4):** `word_mcq` (1), `sentence_cloze` (2), `pattern_cloze` (3), `word_ordering` (4).
- **Target Types (4):** `word` (1), `phrase` (2), `pattern` (3), `sentence` (4).
- **Distractor Quality:** Distractors must match the target's Part-of-Speech (POS) and CEFR level (A1–C2).
- **Database Schema:** `quiz_questions(id, question_type, target_type, target_id, prompt_text, correct_answer, options_json, cefr_level)`.
- **Mobile SQL View:** `v_quiz_questions` JOINing `quiz_questions` and `sentences` to output `quiz_id`, `question_type`, `target_type`, `target_id`, `prompt_text`, `correct_answer`, `options_json`, `cefr_level`, `audio_path`.
- **Latency SLA:** Quiz fetch query response time < 1.0 ms in `SQLiteExporter`.

---

### Task 1: `QuizBuilder` Engine & Smart Distractor Index

**Files:**
- Create: `src/nlp/quiz_builder.py`
- Create: `tests/test_quiz_builder.py`

**Interfaces:**
- Consumes: Word pool, Sentence pool, Sentence Pattern catalog.
- Produces: `QuizBuilder.build_all_quizzes(words, sentences, patterns) -> List[Dict[str, Any]]` returning quiz question payloads.

- [ ] **Step 1: Write failing unit test for `QuizBuilder`**

```python
import json
import pytest
from src.nlp.quiz_builder import QuizBuilder

def test_quiz_builder_generators():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ, từ bỏ"},
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "replace", "pos": "verb", "cefr_level": "B2", "text_vi": "thay thế"},
        {"id": 4, "lemma": "neglect", "pos": "verb", "cefr_level": "B2", "text_vi": "bỏ mặc"},
        {"id": 5, "lemma": "apple", "pos": "noun", "cefr_level": "A1", "text_vi": "quả táo"}
    ]
    sentences = [
        {"id": 10, "text_en": "She decided to abandon her old car.", "text_vi": "Cô ấy quyết định từ bỏ chiếc xe cũ.", "cefr_level": "B2"}
    ]
    patterns = [
        {"id": 100, "pattern_name": "it_is_adj_to_v", "example_en": "It is important to learn English.", "cefr_level": "A2"}
    ]

    builder = QuizBuilder()
    quizzes = builder.build_all_quizzes(words=words, sentences=sentences, patterns=patterns)
    assert len(quizzes) >= 4

    types = {q["question_type"] for q in quizzes}
    assert "word_mcq" in types
    assert "sentence_cloze" in types
    assert "pattern_cloze" in types
    assert "word_ordering" in types

    word_mcq = next(q for q in quizzes if q["question_type"] == "word_mcq")
    options = json.loads(word_mcq["options_json"])
    assert len(options) == 4
    assert word_mcq["correct_answer"] in options
    # Verify distractors are verbs, not nouns
    assert "quả táo" not in options
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quiz_builder.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.nlp.quiz_builder'`).

- [ ] **Step 3: Implement `QuizBuilder` in `src/nlp/quiz_builder.py`**

Create `src/nlp/quiz_builder.py` with `QuizBuilder` class:
- `_index_words(words)` building `pos_cefr_index: Dict[Tuple[str, str], List[Dict]]`.
- Generator methods: `generate_word_mcq`, `generate_sentence_cloze`, `generate_pattern_cloze`, `generate_word_ordering`.
- `build_all_quizzes(words, sentences, patterns)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_quiz_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/quiz_builder.py tests/test_quiz_builder.py
git commit -m "feat(nlp): add QuizBuilder engine with POS and CEFR smart distractor index"
```

---

### Task 2: Database Schema & Batch Insertion Helpers

**Files:**
- Modify: `src/db/staging_db.py`
- Create: `tests/test_quiz_db.py`

**Interfaces:**
- Consumes: Staging DB connection.
- Produces: `DatabaseManager.insert_quiz_questions_batch(questions: List[Dict[str, Any]]) -> int`.

- [ ] **Step 1: Write failing unit test for `insert_quiz_questions_batch`**

```python
import pytest
from src.db.staging_db import DatabaseManager

@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    return db_mgr

def test_insert_quiz_questions_batch(tmp_db):
    questions = [
        {
            "question_type": "word_mcq",
            "target_type": "word",
            "target_id": 1,
            "prompt_text": "abandon",
            "correct_answer": "rời bỏ",
            "options_json": '["rời bỏ", "đạt được", "thay thế", "bỏ mặc"]',
            "cefr_level": "B2"
        }
    ]
    count = tmp_db.insert_quiz_questions_batch(questions)
    assert count == 1

    conn = tmp_db.get_connection()
    row = conn.execute("SELECT question_type, prompt_text, cefr_level FROM quiz_questions WHERE target_id = 1;").fetchone()
    assert row[0] == "word_mcq"
    assert row[1] == "abandon"
    assert row[2] == "B2"
    tmp_db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quiz_db.py -v`
Expected: FAIL (`AttributeError: 'DatabaseManager' object has no attribute 'insert_quiz_questions_batch'`).

- [ ] **Step 3: Implement `quiz_questions` schema and `insert_quiz_questions_batch` in `src/db/staging_db.py`**

In `src/db/staging_db.py`:
- Add `CREATE TABLE IF NOT EXISTS quiz_questions (...)` to `init_schema()`.
- Add `CREATE INDEX IF NOT EXISTS idx_quiz_type_cefr` and `idx_quiz_target`.
- Implement `insert_quiz_questions_batch(self, questions: List[Dict[str, Any]]) -> int`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_quiz_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/staging_db.py tests/test_quiz_db.py
git commit -m "feat(db): add quiz_questions schema and insert_quiz_questions_batch helper"
```

---

### Task 3: ETL Pipeline Integration Step 4E (`main.py`)

**Files:**
- Modify: `main.py`
- Create: `tests/test_quiz_pipeline.py`

**Interfaces:**
- Consumes: Staging database.
- Produces: `run_quiz_step(db_mgr: DatabaseManager) -> int`.

- [ ] **Step 1: Write failing unit test for `run_quiz_step`**

```python
import pytest
from src.db.staging_db import DatabaseManager
from main import run_quiz_step

def test_run_quiz_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    conn = db_mgr.get_connection()
    conn.execute("INSERT INTO words (id, lemma, pos, cefr_level) VALUES (1, 'abandon', 'verb', 'B2');")
    conn.execute("INSERT INTO sentences (id, text_en, text_vi, cefr_level) VALUES (10, 'She abandoned her car.', 'Cô ấy bỏ xe.', 'B2');")
    conn.commit()

    count = run_quiz_step(db_mgr)
    assert count >= 1

    q_count = conn.execute("SELECT COUNT(*) FROM quiz_questions;").fetchone()[0]
    assert q_count == count
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quiz_pipeline.py -v`
Expected: FAIL (`ImportError: cannot import name 'run_quiz_step' from 'main'`).

- [ ] **Step 3: Implement `run_quiz_step` in `main.py`**

Add `run_quiz_step(db_mgr: DatabaseManager, args=None) -> int` to `main.py`:
- Fetch words, sentences, sentence patterns from `db_mgr`.
- Build quiz questions via `QuizBuilder.build_all_quizzes()`.
- Insert into DB via `insert_quiz_questions_batch()`.
- Connect `run_quiz_step` into Step 4E of `run_pipeline()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_quiz_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_quiz_pipeline.py
git commit -m "feat(pipeline): add run_quiz_step to main.py ETL pipeline"
```

---

### Task 4: Mobile Exporter Optimization, Enum Encoding, SQL View & SLA Benchmark

**Files:**
- Modify: `src/export/sqlite_exporter.py`
- Modify: `tests/test_sqlite_exporter.py`

**Interfaces:**
- Consumes: Packaged SQLite database.
- Produces: `v_quiz_questions` SQL View, Integer ENUM conversion, and `quiz_fetch_ms` SLA benchmark < 1.0 ms.

- [ ] **Step 1: Write failing unit test for `v_quiz_questions` view & SLA benchmark**

```python
import sqlite3
import pytest
from src.export.sqlite_exporter import SQLiteExporter

def test_v_quiz_questions_view_and_sla(dummy_db):
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS quiz_questions (id INTEGER PRIMARY KEY, question_type TEXT, target_type TEXT, target_id INTEGER, prompt_text TEXT, correct_answer TEXT, options_json TEXT, cefr_level TEXT);")
    conn.execute("INSERT INTO quiz_questions VALUES (1, 'word_mcq', 'word', 1, 'abandon', 'rời bỏ', '[\"rời bỏ\", \"đạt được\"]', 'B2');")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Verify Integer Enum Migration (word_mcq -> 1, word -> 1, B2 -> integer code)
    row = conn.execute("SELECT question_type, target_type FROM quiz_questions WHERE id = 1;").fetchone()
    assert isinstance(row[0], int)
    assert row[0] == 1
    assert isinstance(row[1], int)
    assert row[1] == 1

    # Verify v_quiz_questions View
    v_row = conn.execute("SELECT quiz_id, prompt_text FROM v_quiz_questions WHERE quiz_id = 1;").fetchone()
    assert v_row is not None
    assert v_row[1] == 'abandon'
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "quiz_fetch_ms" in benchmarks
    assert benchmarks["quiz_fetch_ms"] < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sqlite_exporter.py::test_v_quiz_questions_view_and_sla -v`
Expected: FAIL (assertion error because `v_quiz_questions` view or `quiz_fetch_ms` missing).

- [ ] **Step 3: Implement Integer ENUMs, `v_quiz_questions` view & SLA benchmark in `SQLiteExporter`**

In `src/export/sqlite_exporter.py`:
- Add `QUESTION_TYPE_MAP` and `TARGET_TYPE_MAP`.
- Register `quiz_questions` for enum migration in `_migrate_schema_and_enums`.
- Create `v_quiz_questions` SQL View.
- Add `idx_quiz_cov` covering index.
- Add `quiz_fetch_ms` query benchmark to `benchmark_all_queries`:
  `SELECT quiz_id, prompt_text, correct_answer, options_json FROM v_quiz_questions WHERE question_type = 1 LIMIT 10;`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sqlite_exporter.py::test_v_quiz_questions_view_and_sla -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/sqlite_exporter.py tests/test_sqlite_exporter.py
git commit -m "feat(export): add quiz_questions enum migration, v_quiz_questions view, and quiz_fetch_ms SLA benchmark"
```

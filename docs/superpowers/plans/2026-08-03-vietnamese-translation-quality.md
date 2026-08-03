# Vietnamese Translation Quality & Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate English passthrough in all Vietnamese translation columns and backfill validated Vietnamese translations for prioritized words via a checkpointed Step 4I.

**Architecture:** A pure `VietnameseTextValidator` (heuristic, no I/O) gates all machine translations; `Translator.translate_text` returns `""` instead of passthrough on failure; a one-time cleanup NULLs existing polluted rows; `run_vietnamese_step()` (Step 4I, after 4H) backfills definitions/collocations/phrases with priority ordering and a count-based checkpoint. Mirrors the 4G/4H pattern (direct SQL in main.py, batch 1000, stats dict).

**Adaptations vs spec (authorized):**
- Priority 1 uses `words.cefr_level IS NOT NULL` instead of `audio_status='ok'` — the `words` table has no audio column (audio lives on sentences/phrases).
- No `staging_db.py` changes — the 4G/4H convention runs SQL directly in main.py steps.
- Cleanup compares `definition_vi = definition_en` (exact match) — the ingest pollution wrote the gloss verbatim.

**Tech Stack:** Python 3.14, sqlite3, pytest, deep_translator (existing), no new deps.

**Spec:** `docs/superpowers/specs/2026-08-03-vietnamese-translation-quality-design.md`

**Test command:** `make test` (runs `.venv/bin/pytest -v`). Single test: `.venv/bin/pytest tests/test_vi_validator.py -v`

---

### Task 1: `VietnameseTextValidator` — pure heuristic

**Files:**
- Create: `src/nlp/vi_validator.py`
- Test: `tests/test_vi_validator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vi_validator.py`:

```python
"""
Unit tests for VietnameseTextValidator in src.nlp.vi_validator
"""

import pytest
from src.nlp.vi_validator import VietnameseTextValidator


@pytest.fixture
def validator():
    return VietnameseTextValidator()


def test_accepts_toned_vietnamese(validator):
    assert validator.is_vietnamese("con chó đang chạy") is True
    assert validator.is_vietnamese("Bạn khỏe không?") is True
    assert validator.is_vietnamese("chào buổi sáng") is True


def test_accepts_vietnamese_specific_chars(validator):
    assert validator.is_vietnamese("đi học") is True
    assert validator.is_vietnamese("trường học") is True


def test_rejects_english_with_function_words(validator):
    assert validator.is_vietnamese("The quick brown fox jumps over the lazy dog") is False
    assert validator.is_vietnamese("to be or not to be") is False
    assert validator.is_vietnamese("A small furry animal that says meow") is False


def test_accepts_short_ambiguous_text(validator):
    # No diacritics, no English function words -> accept (avoid false rejects)
    assert validator.is_vietnamese("cat") is True
    assert validator.is_vietnamese("ban") is True


def test_rejects_empty_and_whitespace(validator):
    assert validator.is_vietnamese("") is False
    assert validator.is_vietnamese("   ") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_vi_validator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.nlp.vi_validator'`

- [ ] **Step 3: Create `src/nlp/vi_validator.py`**

```python
"""
Vietnamese Text Validator for English Dataset System Engine.
Pure heuristic (no I/O, no network) that decides whether a text is Vietnamese.
Used to reject English passthrough from machine translation providers.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VietnameseTextValidator:
    """Heuristic validator: Vietnamese-specific chars or tone marks win; otherwise
    English function-word density decides."""

    # Letters that only appear in Vietnamese (plus tone-marked vowels)
    VIETNAMESE_SPECIFIC_CHARS = set("ăâđêôơư")
    TONE_MARKED_VOWELS = set("àáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ")
    ENGLISH_FUNCTION_WORDS = {
        "the", "and", "of", "to", "with", "for", "is", "are",
        "a", "an", "this", "that", "you", "in", "on", "it", "as"
    }

    def is_vietnamese(self, text: Optional[str]) -> bool:
        """True if text is (very likely) Vietnamese, False if it is English passthrough."""
        if not text or not text.strip():
            return False

        clean = text.strip()

        # 1. Vietnamese-specific characters or tone-marked vowels -> accept
        if any(ch in self.VIETNAMESE_SPECIFIC_CHARS for ch in clean) or \
           any(ch in self.TONE_MARKED_VOWELS for ch in clean):
            return True

        # 2. Pure ASCII: count English function words -> reject if >= 2
        words = {w.strip(".,!?;:\"'()[]").lower() for w in clean.split()}
        function_word_hits = len(words & self.ENGLISH_FUNCTION_WORDS)
        if function_word_hits >= 2:
            return False

        # 3. Ambiguous short text -> accept (avoid false rejects)
        return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_vi_validator.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/vi_validator.py tests/test_vi_validator.py
git commit -m "feat(nlp): VietnameseTextValidator heuristic rejects English passthrough"
```

---

### Task 2: Translator — validation gate, no passthrough

**Files:**
- Modify: `src/nlp/translator.py`
- Test: `tests/test_translator.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_translator.py`:

```python
"""
Unit tests for Translator validation behavior in src.nlp.translator
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.nlp.translator import Translator


def make_translator(tmp_path: Path, fake) -> Translator:
    tr = Translator(cache_path=tmp_path / "cache.json")
    tr._translator = fake
    return tr


def test_translate_valid_vietnamese_cached(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "con chó"))
    assert tr.translate_text("dog") == "con chó"
    assert tr.translate_text("dog") == "con chó"  # served from cache


def test_translate_english_passthrough_rejected(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "The dog is an animal"))
    assert tr.translate_text("dog") == ""


def test_translate_retries_once_then_returns_empty(tmp_path: Path):
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            return "The dog is an animal"  # English -> rejected, retry
        return "con chó"

    tr = make_translator(tmp_path, SimpleNamespace(translate=flaky))
    assert tr.translate_text("dog") == "con chó"
    assert calls["n"] == 2


def test_translate_exception_returns_empty(tmp_path: Path):
    def boom(text):
        raise RuntimeError("network down")

    tr = make_translator(tmp_path, SimpleNamespace(translate=boom))
    assert tr.translate_text("dog") == ""


def test_cache_never_stores_passthrough(tmp_path: Path):
    tr = make_translator(tmp_path, SimpleNamespace(translate=lambda text: "The dog is an animal"))
    tr.translate_text("dog")
    assert "dog" not in tr.cache
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_translator.py -v`
Expected: FAIL — current `translate_text` returns passthrough text on failure (`The dog is an animal` instead of `""`), and the exception case raises into the caller.

- [ ] **Step 3: Modify `src/nlp/translator.py`**

Make four exact edits (in order):

**Edit A — add import after `from config.settings import PROCESSED_DATA_DIR` (line 11):**

```python
from src.nlp.vi_validator import VietnameseTextValidator
```

**Edit B — add class constant after the docstring inside `class Translator` (after line 18):**

```python
    MAX_ATTEMPTS = 2  # one initial call + one retry
```

**Edit C — add validator instance in `__init__` (after line 25, `self._translator = None`):**

```python
        self.validator = VietnameseTextValidator()
```

**Edit D — replace the whole `translate_text` method (current lines 52-69):**

```python
    def translate_text(self, text: str) -> str:
        """
        Translates text to Vietnamese, validated by VietnameseTextValidator.
        Returns "" (never English passthrough) on failure or invalid output.
        """
        clean_text = text.strip()
        if not clean_text:
            return ""
        if clean_text in self.cache:
            return self.cache[clean_text]

        t = self._get_translator()
        if t:
            for attempt in range(self.MAX_ATTEMPTS):
                try:
                    translated = t.translate(clean_text)
                    if translated and self.validator.is_vietnamese(translated):
                        self.cache[clean_text] = translated
                        return translated
                except Exception as e:
                    logger.debug("Translation attempt %s failed for '%s': %s",
                                 attempt + 1, clean_text[:30], e)

        return ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_translator.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Run the full suite for regressions**

Run: `.venv/bin/pytest -q`
Expected: ALL PASS (existing `tests/test_phrase_pipeline.py` stubs `Translator` as a class with `translate_text`; it is unaffected)

- [ ] **Step 6: Commit**

```bash
git add src/nlp/translator.py tests/test_translator.py src/nlp/vi_validator.py
git commit -m "feat(nlp): Translator validates Vietnamese output, returns empty instead of passthrough"
```

---

### Task 3: Fix pollution at source — KaikkiParser

**Files:**
- Modify: `src/ingestion/kaikki_parser.py:149`
- Test: `tests/test_ingestion.py` (verify only)

- [ ] **Step 1: Change the fallback**

In `src/ingestion/kaikki_parser.py`, line 149, change:

```python
                    "definition_vi": vi_trans_str or gloss.strip(),
```

to:

```python
                    "definition_vi": vi_trans_str,
```

(The definition stays NULL when no native Vietnamese translation exists — never English gloss.)

- [ ] **Step 2: Verify no test depends on the old behavior**

Run: `.venv/bin/pytest tests/test_ingestion.py -v`
Expected: PASS (no test asserts `definition_vi` — verified before writing this plan)

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/ingestion/kaikki_parser.py
git commit -m "fix(ingestion): no English gloss fallback for definition_vi"
```

---

### Task 4: Step 4I — `run_vietnamese_step` pipeline wiring

**Files:**
- Modify: `main.py`
- Test: `tests/test_vietnamese_pipeline.py` (new)

- [ ] **Step 1: Write the failing end-to-end tests**

Create `tests/test_vietnamese_pipeline.py`:

```python
"""
End-to-end tests for the Step 4I Vietnamese translation backfill stage.
"""

import argparse
from pathlib import Path

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def vi_environment(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # words: dog graded (priority), cat ungraded
    cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('dog', 'noun', 'A1');")
    cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('cat', 'noun', NULL);")
    dog_id = cursor.execute("SELECT id FROM words WHERE lemma='dog'").fetchone()[0]
    cat_id = cursor.execute("SELECT id FROM words WHERE lemma='cat'").fetchone()[0]

    # definitions: dog polluted (vi == en), cat missing
    cursor.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi) VALUES (?, ?, ?);",
        (dog_id, "A loyal animal.", "A loyal animal.")
    )
    cursor.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi) VALUES (?, ?, ?);",
        (cat_id, "A small pet.", None)
    )

    # collocation polluted + phrase polluted
    cursor.execute(
        "INSERT INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level) VALUES (?, ?, 'verb_noun', 'B1');",
        ("take a break", "take a break")
    )
    cursor.execute(
        "INSERT INTO phrases (phrase, phrase_type, definition_en, definition_vi, audio_status) "
        "VALUES ('give up', 'phrasal_verb', 'To stop trying.', 'To stop trying.', 'ok');",
    )
    conn.commit()

    monkeypatch.setattr(main_module, "Translator", StubTranslator)
    yield db_manager
    db_manager.close()


class StubTranslator:
    """Fake Translator used by run_vietnamese_step; override translate_text per test."""

    @staticmethod
    def translate_text(text):
        return f"bản dịch của {text}"


def test_run_vietnamese_step_cleans_and_backfills(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    stats = main_module.run_vietnamese_step(db_manager, args)

    assert stats["definitions"] == 2
    assert stats["collocations"] == 1
    assert stats["phrases"] == 1

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions ORDER BY definition_en;")
    assert {row[0] for row in cursor.fetchall()} == {"bản dịch của A loyal animal.", "bản dịch của A small pet."}
    cursor.execute("SELECT meaning_vi FROM collocations;")
    assert cursor.fetchone()[0] == "bản dịch của take a break"
    cursor.execute("SELECT definition_vi FROM phrases;")
    assert cursor.fetchone()[0] == "bản dịch của To stop trying."


def test_run_vietnamese_step_checkpoint_skips(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    # Fill every candidate first so the checkpoint fires
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE definitions SET definition_vi = 'đã có bản dịch';")
    cursor.execute("UPDATE collocations SET meaning_vi = 'đã có bản dịch';")
    cursor.execute("UPDATE phrases SET definition_vi = 'đã có bản dịch';")
    conn.commit()

    with pytest.MonkeyPatch.context() as mp:
        calls = {"n": 0}
        original = main_module.Translator

        class CountingTranslator:
            def __init__(self):
                calls["n"] += 1

        mp.setattr(main_module, "Translator", CountingTranslator)
        stats = main_module.run_vietnamese_step(db_manager, args)
        mp.undo()

    assert calls["n"] == 0
    assert stats == {"definitions": 0, "collocations": 0, "phrases": 0}


def test_run_vietnamese_step_mt_english_result_stays_null(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    class EnglishTranslator:
        @staticmethod
        def translate_text(text):
            return "The dog is an animal"

    monkeypatch.setattr(main_module, "Translator", EnglishTranslator)

    stats = main_module.run_vietnamese_step(db_manager, args)

    assert stats["definitions"] == 0
    assert stats["collocations"] == 0
    assert stats["phrases"] == 0

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM definitions WHERE definition_vi IS NOT NULL;")
    assert cursor.fetchone()[0] == 0


def test_run_vietnamese_step_idempotent(vi_environment):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    first = main_module.run_vietnamese_step(db_manager, args)
    second = main_module.run_vietnamese_step(db_manager, args)

    assert first["definitions"] == 2
    assert second["definitions"] == 0  # already translated -> checkpoint


def test_run_vietnamese_step_prioritizes_graded_words(vi_environment, monkeypatch):
    db_manager = vi_environment
    args = argparse.Namespace(force_reset=False)

    # Only translate dog's definition (graded); cat stays NULL
    class LimitedTranslator:
        @staticmethod
        def translate_text(text):
            if text == "A loyal animal.":
                return "Một loài vật trung thành."
            return ""  # budget exhausted for ungraded

    monkeypatch.setattr(main_module, "Translator", LimitedTranslator)

    stats = main_module.run_vietnamese_step(db_manager, args)

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions d JOIN words w ON w.id = d.word_id WHERE w.lemma='dog';")
    assert cursor.fetchone()[0] == "Một loài vật trung thành."
    cursor.execute("SELECT definition_vi FROM definitions d JOIN words w ON w.id = d.word_id WHERE w.lemma='cat';")
    assert cursor.fetchone()[0] is None
```

**NOTE on `test_run_vietnamese_step_prioritizes_graded_words`:** the priority ORDER is implemented as a `LIMIT`-free candidate query sorted by priority; when the MT budget is limited the step translates as many as it can in priority order. The test asserts graded (dog) filled first and ungraded (cat) untouched — implementation must sort candidates with graded words first (see Step 3).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_vietnamese_pipeline.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'run_vietnamese_step'`

- [ ] **Step 3: Add `run_vietnamese_step()` to `main.py`**

Add this function after `run_relations_step` (after line 256) in `main.py`:

```python
VI_PRIORITY_SUBSET_CHECKPOINT = 0  # skip when no prioritized candidates remain


def run_vietnamese_step(db_manager, args) -> dict:
    """
    Step 4I: Vietnamese translation quality & backfill.
    Cleans English passthrough rows, then backfills missing Vietnamese
    translations (definitions, collocations, phrases) via Translator,
    priority-ordered (graded words first). Checkpoint: skips when no
    prioritized candidates remain NULL.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # One-time cleanup: English passthrough -> NULL
    cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
    conn.commit()

    # Prioritized candidates: definitions of graded words (cefr_level set)
    cursor.execute("""
        SELECT d.id, d.definition_en FROM definitions d
        JOIN words w ON w.id = d.word_id
        WHERE d.definition_vi IS NULL
          AND w.cefr_level IS NOT NULL
        ORDER BY d.id;
    """)
    priority_definitions = cursor.fetchall()
    cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
    priority_collocations = cursor.fetchall()
    cursor.execute("SELECT id, definition_en FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
    priority_phrases = cursor.fetchall()

    remaining = len(priority_definitions) + len(priority_collocations) + len(priority_phrases)
    if remaining == VI_PRIORITY_SUBSET_CHECKPOINT and not args.force_reset:
        logger.info("[4I] CHECKPOINT DETECTED: no missing Vietnamese translations for prioritized content. Skipping.")
        return {"definitions": 0, "collocations": 0, "phrases": 0}

    logger.info("   [4I] Backfilling Vietnamese translations (%s definitions, %s collocations, %s phrases)...",
                f"{len(priority_definitions):,}", f"{len(priority_collocations):,}", f"{len(priority_phrases):,}")

    translator = Translator()
    translated_defs = 0
    translated_colls = 0
    translated_phrases = 0

    def _backfill(rows, table, id_col, target_col):
        """Translate each row and UPDATE the target column; returns translated count."""
        updated = 0
        for batch_start in range(0, len(rows), 1000):
            batch = rows[batch_start:batch_start + 1000]
            updates = []
            for row_id, text in batch:
                vi = translator.translate_text(text)
                if vi:
                    updates.append((vi, row_id))
            if updates:
                cursor.executemany(
                    f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?;",
                    updates
                )
                conn.commit()
                updated += len(updates)
        return updated

    translated_defs = _backfill(priority_definitions, "definitions", "id", "definition_vi")
    translated_colls = _backfill(priority_collocations, "collocations", "id", "meaning_vi")
    translated_phrases = _backfill(priority_phrases, "phrases", "id", "definition_vi")
    translator.save_cache()

    logger.info("   [4I] Translated: %s definitions, %s collocations, %s phrases (rest kept NULL).",
                f"{translated_defs:,}", f"{translated_colls:,}", f"{translated_phrases:,}")

    return {"definitions": translated_defs, "collocations": translated_colls, "phrases": translated_phrases}
```

- [ ] **Step 4: Wire Step 4I into `run_pipeline()`**

In `main.py`, after the `[4H]` block (after line 585) and before `# Step 5: Export & Optimize SQLite Mobile DB` (line 587), insert:

```python
    # 4I. Vietnamese Translation Quality & Backfill
    logger.info("   [4I] Building Vietnamese Translation Backfill...")
    vi_stats = run_vietnamese_step(db_manager, args)
    logger.info("   [4I] Completed: %s definitions, %s collocations, %s phrases translated.",
                f"{vi_stats['definitions']:,}", f"{vi_stats['collocations']:,}", f"{vi_stats['phrases']:,}")
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_vietnamese_pipeline.py -v`
Expected: all 5 tests PASS

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest -q`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_vietnamese_pipeline.py
git commit -m "feat(pipeline): Step 4I Vietnamese translation quality and prioritized backfill"
```

---

### Task 5: Documentation update

**Files:**
- Modify: `README.md`
- Modify: `docs/dataset_system_architecture.md`

- [ ] **Step 1: Update README**

In `README.md`, in the project structure tree, find the nlp/ line (currently ends with `topic mapper`) and extend it:

```
│   ├── nlp/                 # Lemmatizer, CEFR, Collocations, Reflex, Phrase Engine, Topic Mapper, Vietnamese Validator
```

(Adjust to the actual current tree text — read README.md first; the key change is appending `Vietnamese Validator` to the nlp/ line.)

And in the intro paragraph (line 3), append after the lexical relations item (which currently ends with `18 curated themes)`):

```markdown
, Vietnamese translation quality backfill (dịch tiếng Việt chuẩn hóa, chống English passthrough)
```

- [ ] **Step 2: Update architecture doc**

In `docs/dataset_system_architecture.md`, after the `### Step 4H` subsection and before the Step 5 section, add (following the existing style — read the doc first for the exact heading/format conventions):

```markdown
### Step 4I: Vietnamese Translation Quality & Backfill (Dịch tiếng Việt chuẩn hóa)

Quét toàn bộ dữ liệu có cột dịch tiếng Việt (definitions, collocations, phrases) để:

- Dọn dữ liệu cũ: các row bị English passthrough (definition_vi = definition_en) được đặt lại NULL
- Backfill theo thứ tự ưu tiên: từ đã chấm CEFR (học được) → collocations → phrases
- Mỗi bản dịch MT được kiểm tra bởi `VietnameseTextValidator` (heuristic thuần logic:
  ký tự Việt đặc trưng/thanh điệu → accept; ≥2 từ chức năng Anh + toàn ASCII → reject)
- Kết quả reject/network fail → giữ NULL (không lưu văn bản tiếng Anh)

Checkpoint count-based: chạy lại bỏ qua khi không còn candidates ưu tiên.
Fix tại nguồn: `KaikkiParser` không còn fallback gloss tiếng Anh vào `definition_vi`.
```

- [ ] **Step 3: Verify docs render (no test needed)**

Run: `.venv/bin/pytest tests/test_vietnamese_pipeline.py -v`
Expected: still PASS (docs change only)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/dataset_system_architecture.md
git commit -m "docs: document Step 4I Vietnamese translation quality pipeline"
```

---

### Final verification

- [ ] **Run the full test suite one last time**

Run: `make test`
Expected: ALL PASS (58 existing + new vi_validator/translator/vietnamese_pipeline tests)

- [ ] **Summarize results to the user** — translated counts from a `make run` or dry-run log, test counts, and next steps.

---

## Deviation Log

- **Task 4 (2026-08-03):** Priority 1 uses `words.cefr_level IS NOT NULL` instead of the spec's `audio_status='ok'` — the `words` table has no audio column. Adaptation documented in plan header.
- **Task 4 (2026-08-03):** No `staging_db.py` changes — Step 4I runs SQL directly in main.py following the 4G/4H convention (spec listed a staging_db edit).
- **Task 2 (2026-08-03):** `translate_text` now returns `""` (empty, falsy) instead of passthrough text — callers at main.py:92 and main.py:446 already use falsy-or logic, so behavior stays correct.
- **Task 1 (2026-08-03):** The plan's set-based function-word count (`len(words & ENGLISH_FUNCTION_WORDS)`) failed the plan's own tests ("The quick brown fox..." → unique {the} = 1 → accepted). Changed to occurrence counting; later review found contractions/dashes slipped through ("It's a loyal animal.") → regex tokenization on `[^a-zà-ỹ]+` + `he` added to function-word set. All 7 validator tests pass; "to to" reduplication now rejects (documented tradeoff).
- **Task 2 (2026-08-03):** Cache hits bypassed the validator gate — polluted `translation_cache.json` entries would be served forever. `__init__` now constructs the validator before `_load_cache`, which purges entries failing `is_vietnamese`.
- **Task 4 (2026-08-03):** Three plan-snippet fixes forced by the plan's own tests: (1) candidate query selects ALL NULL `definition_vi` rows ordered graded-first (`ORDER BY (w.cefr_level IS NULL), d.id`) instead of graded-only — `test_run_vietnamese_step_cleans_and_backfills` asserts 2 translated definitions; (2) `_backfill` gates with `validator.is_vietnamese(vi)` in addition to `if vi:` — the English-stub test writes truthy English otherwise; (3) `translator.save_cache()` guarded with `hasattr` — plan's test stubs only implement `translate_text`.
- **Task 4 (2026-08-03):** Polish round: constant renamed `VI_PRIORITY_SUBSET_CHECKPOINT` → `VI_EMPTY_BACKFILL_CHECKPOINT` (semantics now all-NULL-rows, not subset); `save_cache()` moved to after each table backfill; per-10-batch progress logging (4G/4H convention); SQL interpolation safety comment; priority test now fails if ungraded rows are processed first (BudgetTranslator).

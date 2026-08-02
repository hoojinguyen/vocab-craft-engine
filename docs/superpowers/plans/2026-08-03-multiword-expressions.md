# Multi-Word Expressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest idioms, phrasal verbs, proverbs and fixed expressions from the Kaikki dump into `english_dataset.db` with CEFR grades, Tatoeba example sentences, Vietnamese translations and dual-speed TTS audio.

**Architecture:** Follows the existing module pattern — a `PhraseParser` re-streams the Kaikki dump (which currently drops multi-word entries at `kaikki_parser.py:67`), a `PhraseGrader` reuses `CEFRGrader.grade_sentence` on content words, and a `PhraseExampleMatcher` links Tatoeba sentences via a word index with boundary-safe matching. New tables `phrases` + `phrase_sentences` follow the `word_sentence_map` junction pattern. The pipeline step is extracted into a callable `run_phrase_step()` in `main.py` so it can be tested end-to-end without running the whole pipeline.

**Tech Stack:** Python 3.14, sqlite3, ijson, edge-tts, pytest (asyncio support), existing `config/settings.py`.

**Spec:** `docs/superpowers/specs/2026-08-03-multiword-expressions-design.md`

**Test command:** `make test` (runs `.venv/bin/pytest -v`). Single test: `.venv/bin/pytest tests/test_phrase_parser.py::test_name -v`

---

### Task 1: Schema — `phrases` & `phrase_sentences` tables + DB methods

**Files:**
- Modify: `src/db/staging_db.py`
- Test: `tests/test_staging_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_staging_db.py`:

```python
def test_phrase_tables_exist(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"phrases", "phrase_sentences"}.issubset(tables)


def test_insert_phrases_batch_and_idempotency(temp_db: DatabaseManager):
    phrases = [
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": "Chúc may mắn!", "ipa": "breɪk ə leɡ",
         "audio_std": None, "audio_fast": None, "audio_status": "ok"},
        {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "phrasal verb",
         "cefr_level": "A2", "difficulty_score": 1.8, "definition_en": "To stop trying.",
         "definition_vi": "Từ bỏ", "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ]
    temp_db.insert_phrases_batch(phrases)

    assert temp_db.get_phrase_id_by_text("break a leg") is not None
    assert temp_db.get_phrase_id_by_text("give up") is not None

    # Idempotency: INSERT OR IGNORE on duplicate phrase
    temp_db.insert_phrases_batch(phrases)
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM phrases;")
    assert cursor.fetchone()[0] == 2


def test_insert_phrase_sentences_batch_and_update_audio(temp_db: DatabaseManager):
    temp_db.insert_phrases_batch([
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    temp_db.insert_sentences_batch([
        {"text_en": "Break a leg at the show tonight!", "text_vi": None,
         "difficulty_score": 2.0, "cefr_level": "B1", "audio_path": None, "source": "Tatoeba"}
    ])
    phrase_id = temp_db.get_phrase_id_by_text("break a leg")

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sentences WHERE text_en = ?;", ("Break a leg at the show tonight!",))
    sentence_id = cursor.fetchone()[0]

    temp_db.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": sentence_id, "rank": 1}
    ])
    temp_db.update_phrase_audio(phrase_id, "audio/break_1_std.mp3", "audio/break_1_fast.mp3", "ok")

    cursor.execute("SELECT audio_std, audio_fast, audio_status FROM phrases WHERE id = ?;", (phrase_id,))
    row = cursor.fetchone()
    assert row == ("audio/break_1_std.mp3", "audio/break_1_fast.mp3", "ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_staging_db.py::test_phrase_tables_exist tests/test_staging_db.py::test_insert_phrases_batch_and_idempotency tests/test_staging_db.py::test_insert_phrase_sentences_batch_and_update_audio -v`
Expected: FAIL — `sqlite3.OperationalError: no such table: phrases`

- [ ] **Step 3: Add the two tables + indexes to `init_schema`**

In `src/db/staging_db.py`, inside `init_schema()` after the `word_sentence_map` table block (line 152) and before the `# Indexes` comment, add:

```python
        # 10. Phrases table (multi-word expressions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE NOT NULL,
                phrase_type TEXT NOT NULL,
                pos TEXT,
                cefr_level TEXT,
                difficulty_score REAL,
                definition_en TEXT,
                definition_vi TEXT,
                ipa TEXT,
                audio_std TEXT,
                audio_fast TEXT,
                audio_status TEXT DEFAULT 'ok'
            );
        """)

        # 11. Phrase - Sentence Map table (N - N)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phrase_sentences (
                phrase_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                rank INTEGER,
                PRIMARY KEY (phrase_id, sentence_id),
                FOREIGN KEY (phrase_id) REFERENCES phrases (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
            );
        """)
```

After the existing index block (after line 158), add:

```python
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);")
```

- [ ] **Step 4: Add the DB methods**

Append to `src/db/staging_db.py` (after `get_word_id_by_lemma` at the end of the class):

```python
    def insert_phrases_batch(self, phrases_data: List[Dict[str, Any]]) -> int:
        """Batch insert phrases into `phrases` table with IGNORE on duplicate phrase."""
        if not phrases_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO phrases
            (phrase, phrase_type, pos, cefr_level, difficulty_score, definition_en,
             definition_vi, ipa, audio_std, audio_fast, audio_status)
            VALUES (:phrase, :phrase_type, :pos, :cefr_level, :difficulty_score,
                    :definition_en, :definition_vi, :ipa, :audio_std, :audio_fast, :audio_status);
        """
        cursor = conn.cursor()
        cursor.executemany(query, phrases_data)
        conn.commit()
        return cursor.rowcount

    def get_phrase_id_by_text(self, phrase: str) -> Optional[int]:
        """Fetch phrase_id for a given phrase text."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM phrases WHERE phrase = ? LIMIT 1;", (phrase,))
        row = cursor.fetchone()
        return row[0] if row else None

    def insert_phrase_sentences_batch(self, mappings_data: List[Dict[str, Any]]) -> int:
        """Batch insert mappings into `phrase_sentences` table."""
        if not mappings_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO phrase_sentences (phrase_id, sentence_id, rank)
            VALUES (:phrase_id, :sentence_id, :rank);
        """
        cursor = conn.cursor()
        cursor.executemany(query, mappings_data)
        conn.commit()
        return cursor.rowcount

    def update_phrase_audio(self, phrase_id: int, audio_std: Optional[str],
                            audio_fast: Optional[str], audio_status: str = "ok") -> None:
        """Update audio paths and status for a phrase."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;",
            (audio_std, audio_fast, audio_status, phrase_id)
        )
        conn.commit()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_staging_db.py -v`
Expected: all tests PASS (including the 3 pre-existing ones — `test_foreign_key_check` must stay green)

- [ ] **Step 6: Commit**

```bash
git add src/db/staging_db.py tests/test_staging_db.py
git commit -m "feat(db): phrases and phrase_sentences schema with batch methods"
```

---

### Task 2: `KaikkiParser.parse_raw_items()` — unfiltered raw stream

**Files:**
- Modify: `src/ingestion/kaikki_parser.py`
- Test: `tests/test_phrase_parser.py` (created in Task 3 — write the test here first)

- [ ] **Step 1: Write the failing test**

Create `tests/test_phrase_parser.py`:

```python
"""
Unit tests for PhraseParser and KaikkiParser raw streaming
"""

import json
import pytest
from pathlib import Path
from src.ingestion.kaikki_parser import KaikkiParser
from src.ingestion.phrase_parser import PhraseParser


@pytest.fixture
def kaikki_jsonl(tmp_path: Path) -> Path:
    entries = [
        {
            "word": "break a leg",
            "pos": "idiom",
            "sounds": [{"ipa": "breɪk ə leɡ", "tags": ["US"]}],
            "translations": [{"code": "vi", "word": "chúc may mắn"}],
            "senses": [{"glosses": ["A phrase of encouragement."]}]
        },
        {
            "word": "give up",
            "pos": "phrasal verb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["To stop trying."]}]
        },
        {
            "word": "all that glitters is not gold",
            "pos": "proverb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Appearances are deceptive."]}]
        },
        {
            "word": "cat",
            "pos": "noun",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["A small furry animal."]}]
        },
        {
            "word": "too many cooks spoil the broth",
            "pos": "proverb",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Too many people on a task."]}]
        },
        {
            "word": "a very long multi word expression that nobody uses at all",
            "pos": "phrase",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Nonsense."]}]
        },
        {
            "word": "no definition here",
            "pos": "idiom",
            "sounds": [],
            "translations": [],
            "senses": []
        },
        {
            "word": "break 1 leg",
            "pos": "idiom",
            "sounds": [],
            "translations": [],
            "senses": [{"glosses": ["Contains a digit, must be rejected."]}]
        }
    ]
    f = tmp_path / "kaikki_sample.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return f


def test_parse_raw_items_yields_unfiltered_dicts(kaikki_jsonl: Path):
    parser = KaikkiParser(kaikki_jsonl)
    items = list(parser.parse_raw_items())
    assert len(items) == 8
    assert items[0]["word"] == "break a leg"
    assert items[3]["word"] == "cat"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_phrase_parser.py::test_parse_raw_items_yields_unfiltered_dicts -v`
Expected: FAIL with `AttributeError: 'KaikkiParser' object has no attribute 'parse_raw_items'`

- [ ] **Step 3: Add `parse_raw_items` to `KaikkiParser`**

In `src/ingestion/kaikki_parser.py`, add this method after `_parse_json_lines` (line 60), before `extract_fields`:

```python
    def parse_raw_items(self) -> Iterator[Dict[str, Any]]:
        """
        Yields raw (unfiltered) dictionary items, detecting JSON Lines vs JSON array.
        Used by consumers that need multi-word entries (e.g. PhraseParser).
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"Kaikki dump not found at {self.file_path}")

        with open(self.file_path, "r", encoding="utf-8") as f:
            first_char = f.read(1).strip()

        if first_char == "[":
            with open(self.file_path, "rb") as f:
                for item in ijson.items(f, "item"):
                    if isinstance(item, dict):
                        yield item
        else:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            yield item
                    except json.JSONDecodeError:
                        continue
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_phrase_parser.py::test_parse_raw_items_yields_unfiltered_dicts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/kaikki_parser.py tests/test_phrase_parser.py
git commit -m "feat(ingestion): KaikkiParser raw item streaming for multi-word entries"
```

---

### Task 3: `PhraseParser` — multi-word expression extraction

**Files:**
- Create: `src/ingestion/phrase_parser.py`
- Test: `tests/test_phrase_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phrase_parser.py`:

```python
def test_phrase_parser_extracts_only_valid_multiword(kaikki_jsonl: Path):
    parser = PhraseParser(kaikki_jsonl)
    phrases = list(parser.parse_phrases())

    by_phrase = {p["phrase"]: p for p in phrases}
    assert "break a leg" in by_phrase
    assert "give up" in by_phrase
    assert "all that glitters is not gold" in by_phrase

    # Reject single-word, >6 word non-proverb, no-definition entries
    assert "cat" not in by_phrase
    assert "a very long multi word expression that nobody uses at all" not in by_phrase
    assert "no definition here" not in by_phrase

    # Proverb longer than 6 words IS kept
    assert "too many cooks spoil the broth" in by_phrase

    # Field extraction
    leg = by_phrase["break a leg"]
    assert leg["phrase_type"] == "idiom"
    assert leg["definition_en"] == "A phrase of encouragement."
    assert leg["definition_vi"] == "chúc may mắn"
    assert leg["ipa"] == "breɪk ə leɡ"

    up = by_phrase["give up"]
    assert up["phrase_type"] == "phrasal_verb"


def test_phrase_parser_rejects_unclean_chars(kaikki_jsonl: Path):
    parser = PhraseParser(kaikki_jsonl)
    # "break 1 leg" contains a digit -> must be rejected (quality filter)
    phrases = list(parser.parse_phrases())
    by_phrase = {p["phrase"]: p for p in phrases}
    assert "break 1 leg" not in by_phrase

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_phrase_parser.py::test_phrase_parser_extracts_only_valid_multiword -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ingestion.phrase_parser'`

- [ ] **Step 3: Create `src/ingestion/phrase_parser.py`**

```python
"""
Multi-Word Expression Parser for English Dataset System Engine.
Extracts idioms, phrasal verbs, proverbs and fixed expressions from Kaikki dump entries.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Dict, Any, Optional

from src.ingestion.kaikki_parser import KaikkiParser

logger = logging.getLogger(__name__)

PHRASE_POS_ALLOWED = {"idiom", "phrasal verb", "proverb", "phrase"}
MAX_WORDS = 6
# Only letters, spaces, hyphens, apostrophes and periods are allowed
CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")


class PhraseParser:
    """Parses multi-word expressions from Kaikki dump entries (streaming)."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    @staticmethod
    def extract_phrase_fields(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        word = item.get("word", "").strip().lower()
        if not word or " " not in word:
            return None

        pos = item.get("pos", "").strip().lower()
        if pos not in PHRASE_POS_ALLOWED:
            return None

        if len(word.split()) > MAX_WORDS and pos != "proverb":
            return None

        # Quality filter: reject digits and special characters
        if not CLEAN_CHARS_PATTERN.match(word):
            return None

        # Extract first IPA transcription
        ipa = None
        for sound in item.get("sounds", []):
            sound_ipa = sound.get("ipa")
            if sound_ipa:
                ipa = sound_ipa
                break

        # Extract Vietnamese translations
        vi_translations = []
        for trans in item.get("translations", []):
            if isinstance(trans, dict):
                lang_code = trans.get("code") or trans.get("lang_code")
                lang_name = trans.get("lang")
                if lang_code == "vi" or lang_name == "Vietnamese":
                    vi_word = trans.get("word", "").strip()
                    if vi_word and vi_word not in vi_translations:
                        vi_translations.append(vi_word)
        vi_trans_str = ", ".join(vi_translations) if vi_translations else None

        # Extract first definition gloss
        definition_en = None
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            for gloss in glosses:
                gloss_text = gloss.strip()
                if gloss_text:
                    definition_en = gloss_text
                    break
            if definition_en:
                break

        if not definition_en:
            return None

        return {
            "phrase": word,
            "phrase_type": pos.replace(" ", "_"),
            "pos": pos,
            "definition_en": definition_en,
            "definition_vi": vi_trans_str,
            "ipa": ipa
        }

    def parse_phrases(self) -> Iterator[Dict[str, Any]]:
        """Yields parsed multi-word expression dicts."""
        kaikki = KaikkiParser(self.file_path)
        for item in kaikki.parse_raw_items():
            parsed = self.extract_phrase_fields(item)
            if parsed:
                yield parsed
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_phrase_parser.py -v`
Expected: both tests PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS (existing `tests/test_ingestion.py` exercises the old `parse_stream` — it must stay green)

- [ ] **Step 6: Commit**

```bash
git add src/ingestion/phrase_parser.py tests/test_phrase_parser.py
git commit -m "feat(ingestion): PhraseParser extracts idioms, phrasal verbs and proverbs"
```

---

### Task 4: `PhraseGrader` — component-based CEFR grading

**Files:**
- Create: `src/nlp/phrase_grader.py`
- Test: `tests/test_phrase_grader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phrase_grader.py`:

```python
"""
Unit tests for PhraseGrader in src.nlp.phrase_grader
"""

import pytest
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.phrase_grader import PhraseGrader


@pytest.fixture
def grader():
    freq_dict = {
        "break": 100, "leg": 300,          # both A1
        "wool": 12000, "eyes": 2000,       # wool B2, eyes A2
        "pull": 800, "someone": 1500,
        "gold": 4000, "glitters": 18000,   # gold A2, glitters C1
        "give": 50, "cat": 6000,
        "a": 1, "an": 2, "the": 3, "of": 4 # stopwords — must exist so fallback grading stays A1
    }
    cefr = CEFRGrader(freq_dict)
    return PhraseGrader(cefr)


def test_grade_phrase_easy_idiom(grader: PhraseGrader):
    result = grader.grade_phrase("break a leg")
    assert result["cefr_level"] in ("A1", "A2")
    assert result["difficulty_score"] >= 1.0


def test_grade_phrase_hard_idiom(grader: PhraseGrader):
    result = grader.grade_phrase("pull the wool over someone's eyes")
    assert result["cefr_level"] in ("B2", "C1", "C2")
    assert result["difficulty_score"] > grader.grade_phrase("break a leg")["difficulty_score"]


def test_grade_phrase_returns_expected_keys(grader: PhraseGrader):
    result = grader.grade_phrase("give up")
    assert set(result.keys()) == {"difficulty_score", "cefr_level", "word_count"}


def test_grade_phrase_all_stopwords_uses_raw_tokens(grader: PhraseGrader):
    result = grader.grade_phrase("a an the of")
    assert result["word_count"] == 4
    assert result["cefr_level"] == "A1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_phrase_grader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.nlp.phrase_grader'`

- [ ] **Step 3: Create `src/nlp/phrase_grader.py`**

```python
"""
CEFR Phrase Grader for English Dataset System Engine.
Grades multi-word expressions using constituent word frequency ranks (reuses CEFRGrader).
"""

import logging
from typing import Dict, Any, Set

from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "by",
    "from", "up", "down", "out", "off", "over", "under", "and", "or", "but",
    "be", "is", "are", "was", "were", "do", "does", "did", "have", "has",
    "had", "as", "so", "if", "it", "its", "my", "your", "his", "her",
    "our", "their", "me", "you", "him", "us", "them", "not", "no", "yes"
}


class PhraseGrader:
    """Assigns CEFR levels and difficulty scores to multi-word expressions."""

    def __init__(self, cefr_grader: CEFRGrader, stopwords: Set[str] = STOPWORDS):
        self.cefr_grader = cefr_grader
        self.stopwords = stopwords

    def grade_phrase(self, phrase: str) -> Dict[str, Any]:
        """
        Grades a phrase from its constituent content words.
        Returns {'cefr_level', 'difficulty_score', 'word_count'} —
        same shape as CEFRGrader.grade_sentence.
        """
        tokens = [w.lower().strip(".,!?;:\"'()[]-") for w in phrase.split()]
        content_words = [w for w in tokens if w and w not in self.stopwords]
        if not content_words:
            content_words = tokens

        return self.cefr_grader.grade_sentence(" ".join(content_words))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_phrase_grader.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/phrase_grader.py tests/test_phrase_grader.py
git commit -m "feat(nlp): PhraseGrader grades multi-word expressions via constituent words"
```

---

### Task 5: `PhraseExampleMatcher` — Tatoeba sentence linking

**Files:**
- Create: `src/nlp/phrase_example_matcher.py`
- Test: `tests/test_phrase_example_matcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_phrase_example_matcher.py`:

```python
"""
Unit tests for PhraseExampleMatcher in src.nlp.phrase_example_matcher
"""

import pytest
from src.nlp.phrase_example_matcher import PhraseExampleMatcher


@pytest.fixture
def sentence_pool():
    return [
        {"id": 1, "text_en": "Break a leg at the show tonight!", "cefr_level": "B1"},
        {"id": 2, "text_en": "She told me to break a leg before the exam.", "cefr_level": "B2"},
        {"id": 3, "text_en": "I finally decided to give up smoking.", "cefr_level": "A2"},
        {"id": 4, "text_en": "Please do not give upward pressure to the door.", "cefr_level": "C1"},
        {"id": 5, "text_en": "He gave up the fight after ten minutes.", "cefr_level": "B1"},
        {"id": 6, "text_en": "A short unrelated sentence.", "cefr_level": "A1"}
    ]


def test_match_phrase_ranks_easy_sentences_first(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("break a leg", phrase_id=10)

    assert [r["phrase_id"] for r in result] == [10, 10]
    assert [r["sentence_id"] for r in result] == [1, 2]
    assert [r["rank"] for r in result] == [1, 2]


def test_match_phrase_boundary_rejects_partial_word(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("give up", phrase_id=20)

    # Sentence 4 contains "give upward" -> boundary mismatch, must be excluded
    sentence_ids = [r["sentence_id"] for r in result]
    assert 4 not in sentence_ids
    assert 3 in sentence_ids
    assert 5 in sentence_ids


def test_match_phrase_no_match_returns_empty(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    result = matcher.match_phrase("pull the wool over someone's eyes", phrase_id=30)
    assert result == []


def test_match_phrase_caps_at_five():
    pool = [{"id": i, "text_en": f"sample phrase number {i} here", "cefr_level": "A1"} for i in range(1, 20)]
    matcher = PhraseExampleMatcher(pool)
    result = matcher.match_phrase("sample phrase", phrase_id=40)
    assert len(result) == 5


def test_match_phrases_batch(sentence_pool):
    matcher = PhraseExampleMatcher(sentence_pool)
    phrases = [{"id": 10, "phrase": "break a leg"}, {"id": 20, "phrase": "give up"}]
    result = matcher.match_phrases(phrases)
    assert len(result) == 4
    assert {r["phrase_id"] for r in result} == {10, 20}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_phrase_example_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.nlp.phrase_example_matcher'`

- [ ] **Step 3: Create `src/nlp/phrase_example_matcher.py`**

```python
"""
Tatoeba Example Sentence Matcher for English Dataset System Engine.
Links multi-word expressions to example sentences with boundary-safe matching
and CEFR-priority ranking (easy sentences first).
"""

import logging
from typing import Dict, Any, List

from src.nlp.phrase_grader import STOPWORDS

logger = logging.getLogger(__name__)

MAX_EXAMPLES_PER_PHRASE = 5
CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}


class PhraseExampleMatcher:
    """Finds example sentences containing a given phrase, ranked by difficulty."""

    def __init__(self, sentences: List[Dict[str, Any]]):
        self.sentences = sentences
        self._word_index: Dict[str, List[Dict[str, Any]]] = {}
        self._build_index()

    def _build_index(self):
        """Index sentences by each word they contain (first-word lookup for candidates)."""
        for sent in self.sentences:
            text = sent["text_en"].lower()
            for word in set(text.split()):
                key = word.strip(".,!?;:\"'()[]")
                if key:
                    self._word_index.setdefault(key, []).append(sent)

    @staticmethod
    def _is_boundary_match(phrase: str, sentence: str) -> bool:
        """True if phrase occurs in sentence not surrounded by alphanumeric chars."""
        start = sentence.find(phrase)
        while start != -1:
            end = start + len(phrase)
            before_ok = start == 0 or not sentence[start - 1].isalnum()
            after_ok = end == len(sentence) or not sentence[end].isalnum()
            if before_ok and after_ok:
                return True
            start = sentence.find(phrase, start + 1)
        return False

    def match_phrase(self, phrase: str, phrase_id: int) -> List[Dict[str, Any]]:
        """
        Returns up to MAX_EXAMPLES_PER_PHRASE mapping dicts
        {'phrase_id', 'sentence_id', 'rank'} for matching sentences.
        """
        words = [w.strip(".,!?;:\"'()[]") for w in phrase.lower().split()]
        key_words = [w for w in words if w and w not in STOPWORDS] or words
        if not key_words:
            return []

        candidates = self._word_index.get(key_words[0], [])
        matches = [
            sent for sent in candidates
            if self._is_boundary_match(phrase, sent["text_en"].lower())
        ]
        matches.sort(key=lambda s: CEFR_ORDER.get(s.get("cefr_level"), 2))

        return [
            {"phrase_id": phrase_id, "sentence_id": sent["id"], "rank": i + 1}
            for i, sent in enumerate(matches[:MAX_EXAMPLES_PER_PHRASE])
        ]

    def match_phrases(self, phrases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Matches a list of {'id', 'phrase'} dicts, returning all mappings."""
        results: List[Dict[str, Any]] = []
        for phrase_item in phrases:
            results.extend(
                self.match_phrase(phrase_item["phrase"], phrase_item["id"])
            )
        return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_phrase_example_matcher.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/phrase_example_matcher.py tests/test_phrase_example_matcher.py
git commit -m "feat(nlp): PhraseExampleMatcher links phrases to ranked Tatoeba sentences"
```

---

### Task 6: `AudioGenerator.generate_dual_speed_phrase`

**Files:**
- Modify: `src/media/audio_generator.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_media.py`:

```python
@pytest.mark.asyncio
async def test_audio_generator_dual_speed_phrase(tmp_path: Path):
    audio_gen = AudioGenerator(output_dir=tmp_path, max_concurrent=2, retry_count=1)

    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        res = await audio_gen.generate_dual_speed_phrase(
            phrase_id=7,
            text_en="break a leg"
        )

        assert res["standard_path"] is not None
        assert res["fast_path"] is not None
        assert res["standard_path"].name == "phrase_7_std.mp3"
        assert res["fast_path"].name == "phrase_7_fast.mp3"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_media.py::test_audio_generator_dual_speed_phrase -v`
Expected: FAIL with `AttributeError: 'AudioGenerator' object has no attribute 'generate_dual_speed_phrase'`

- [ ] **Step 3: Add the method to `AudioGenerator`**

In `src/media/audio_generator.py`, after `generate_dual_speed_sentence` (line 94), add:

```python
    async def generate_dual_speed_phrase(
        self,
        phrase_id: int,
        text_en: str,
        voice: str = TTS_VOICES["US_FEMALE"]
    ) -> Dict[str, Optional[Path]]:
        """
        Generates standard (1.0x) and fast reflex (1.2x) audio files for a phrase.
        Uses phrase_{id}_*.mp3 naming to avoid collision with sentence audio.
        """
        fn_std = f"phrase_{phrase_id}_std.mp3"
        fn_fast = f"phrase_{phrase_id}_fast.mp3"

        std_path, fast_path = await asyncio.gather(
            self.generate_audio_file(text_en, fn_std, voice=voice, speed=TTS_SPEED_STANDARD),
            self.generate_audio_file(text_en, fn_fast, voice=voice, speed=TTS_SPEED_FAST_REFLEX)
        )

        return {
            "standard_path": std_path,
            "fast_path": fast_path
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_media.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/media/audio_generator.py tests/test_media.py
git commit -m "feat(media): dual-speed TTS audio generation for phrases"
```

---

### Task 7: Exporter — phrase indexes

**Files:**
- Modify: `src/export/sqlite_exporter.py`
- Test: `tests/test_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export.py`:

```python
def test_exporter_creates_phrase_indexes(populated_db: Path):
    db_manager = DatabaseManager(db_path=populated_db)
    db_manager.init_schema()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # Insert one phrase + one sentence mapping so indexes have data
    db_manager.insert_phrases_batch([
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    phrase_id = db_manager.get_phrase_id_by_text("break a leg")
    db_manager.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": 1, "rank": 1}
    ])
    db_manager.close()

    exporter = SQLiteExporter(db_path=populated_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(populated_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN ('phrases', 'phrase_sentences');")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_phrases_cefr" in indexes
    assert "idx_phrases_type" in indexes
    assert "idx_phrase_sentences_phrase" in indexes
    assert "idx_phrase_sentences_sentence" in indexes


def test_exporter_phrase_foreign_keys(populated_db: Path):
    db_manager = DatabaseManager(db_path=populated_db)
    db_manager.init_schema()
    db_manager.insert_phrases_batch([
        {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "phrasal verb",
         "cefr_level": "A2", "difficulty_score": 1.8, "definition_en": "Stop trying.",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    phrase_id = db_manager.get_phrase_id_by_text("give up")
    db_manager.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": 1, "rank": 1}
    ])
    db_manager.close()

    exporter = SQLiteExporter(db_path=populated_db)
    violations = exporter.verify_foreign_keys()
    assert len(violations) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: FAIL — `idx_phrases_cefr` etc. missing after `optimize_and_package`

- [ ] **Step 3: Add the indexes to `optimize_and_package`**

In `src/export/sqlite_exporter.py`, after line 42 (`idx_nodes_tree_parent`), add:

```python
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: all tests PASS (including the 2 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/export/sqlite_exporter.py tests/test_export.py
git commit -m "feat(export): phrase indexes in mobile SQLite packaging"
```

---

### Task 8: Pipeline wiring — `main.py` Step 4G

**Files:**
- Modify: `main.py`
- Test: `tests/test_phrase_pipeline.py` (new)

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/test_phrase_pipeline.py`:

```python
"""
End-to-end test for the Step 4G multi-word expression pipeline stage.
"""

import json
import argparse
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def phrase_environment(tmp_path: Path, monkeypatch):
    # Sample Kaikki dump with multi-word entries
    kaikki_file = tmp_path / "kaikki.jsonl"
    entries = [
        {"word": "break a leg", "pos": "idiom", "sounds": [],
         "translations": [{"code": "vi", "word": "chúc may mắn"}],
         "senses": [{"glosses": ["A phrase of encouragement."]}]},
        {"word": "give up", "pos": "phrasal verb", "sounds": [],
         "translations": [],
         "senses": [{"glosses": ["To stop trying."]}]},
        {"word": "cat", "pos": "noun", "sounds": [],
         "translations": [], "senses": [{"glosses": ["An animal."]}]}
    ]
    kaikki_file.write_text(
        "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
    )

    # Sample SUBTLEX frequency CSV
    freq_file = tmp_path / "SUBTLEX_US.csv"
    freq_file.write_text(
        "Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW\n"
        "break,50000,125.4,4.7,1000,3.0\n"
        "leg,30000,90.0,4.4,800,2.9\n"
        "give,40000,110.0,4.5,900,2.9\n"
        "cat,20000,50.0,4.0,500,2.7\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(main_module, "KAIKKI_JSON_PATH", kaikki_file)
    monkeypatch.setattr(main_module, "SUBTLEX_FREQ_PATH", freq_file)

    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    db_manager.insert_sentences_batch([
        {"text_en": "Break a leg at the show tonight!", "text_vi": None,
         "difficulty_score": 2.0, "cefr_level": "B1", "audio_path": None, "source": "Tatoeba"},
        {"text_en": "I decided to give up smoking.", "text_vi": None,
         "difficulty_score": 1.5, "cefr_level": "A2", "audio_path": None, "source": "Tatoeba"}
    ])

    # Stub Translator to avoid network calls
    class StubTranslator:
        def translate_text(self, text):
            return text

    monkeypatch.setattr(main_module, "Translator", StubTranslator)

    yield db_manager, db_path
    db_manager.close()


def test_run_phrase_step_populates_db(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Mock edge-tts to avoid network calls during audio generation
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
        async def mock_save_side_effect(target_path):
            Path(target_path).write_bytes(b"MOCK_MP3_DATA")

        mock_save.side_effect = mock_save_side_effect

        stats = main_module.run_phrase_step(db_manager, args)

    assert stats["phrases"] == 2

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phrase, phrase_type, cefr_level, definition_vi FROM phrases ORDER BY phrase;")
    rows = cursor.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "break a leg"
    assert rows[0][1] == "idiom"
    assert rows[0][3] == "chúc may mắn"
    assert rows[1][0] == "give up"
    assert rows[1][1] == "phrasal_verb"

    # Example sentence links
    cursor.execute("SELECT COUNT(*) FROM phrase_sentences;")
    assert cursor.fetchone()[0] >= 2

    # Audio status recorded
    cursor.execute("SELECT audio_status FROM phrases;")
    statuses = {row[0] for row in cursor.fetchall()}
    assert statuses == {"ok"}


def test_run_phrase_step_checkpoint_skips(phrase_environment, monkeypatch):
    db_manager, db_path = phrase_environment
    args = argparse.Namespace(force_reset=False)

    # Pre-populate enough phrases to trigger the checkpoint
    phrases = [
        {"phrase": f"checkpoint phrase {i}", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.0, "definition_en": "x",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
        for i in range(600)
    ]
    db_manager.insert_phrases_batch(phrases)

    with patch.object(main_module, "PhraseParser") as mock_parser:
        stats = main_module.run_phrase_step(db_manager, args)
        mock_parser.assert_not_called()

    assert stats["phrases"] == 600
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_phrase_pipeline.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'run_phrase_step'`

- [ ] **Step 3: Add `run_phrase_step()` to `main.py`**

Add these imports to the import block in `main.py` (after the existing `from src.export.sqlite_exporter import SQLiteExporter` line):

```python
from src.ingestion.phrase_parser import PhraseParser
from src.nlp.phrase_grader import PhraseGrader
from src.nlp.phrase_example_matcher import PhraseExampleMatcher
```

Add this function after `parse_arguments()`:

```python
def run_phrase_step(db_manager, args) -> dict:
    """
    Step 4G: Ingest multi-word expressions (idioms, phrasal verbs, proverbs)
    from the Kaikki dump, grade CEFR, link Tatoeba examples, generate audio.
    Count-based checkpoint: skips when > 500 phrases already exist.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM phrases;")
    existing_phrases = cursor.fetchone()[0]

    if existing_phrases > 500 and not args.force_reset:
        logger.info("[4G] CHECKPOINT DETECTED: %s phrases already exist. Skipping.", f"{existing_phrases:,}")
        return {"phrases": existing_phrases, "links": 0}

    logger.info("   [4G] Ingesting Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs)...")
    phrase_parser = PhraseParser(KAIKKI_JSON_PATH)
    grader = PhraseGrader(CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH))
    translator = Translator()

    phrases_batch = []
    phrase_count = 0
    for item in phrase_parser.parse_phrases():
        graded = grader.grade_phrase(item["phrase"])
        phrases_batch.append({
            "phrase": item["phrase"],
            "phrase_type": item["phrase_type"],
            "pos": item["pos"],
            "cefr_level": graded["cefr_level"],
            "difficulty_score": graded["difficulty_score"],
            "definition_en": item["definition_en"],
            "definition_vi": item.get("definition_vi") or translator.translate_text(item["phrase"]),
            "ipa": item.get("ipa"),
            "audio_std": None,
            "audio_fast": None,
            "audio_status": "ok"
        })

        if len(phrases_batch) >= 1000:
            db_manager.insert_phrases_batch(phrases_batch)
            phrase_count += len(phrases_batch)
            phrases_batch = []
            logger.info("   -> Staged %s phrases...", f"{phrase_count:,}")

    if phrases_batch:
        db_manager.insert_phrases_batch(phrases_batch)
        phrase_count += len(phrases_batch)
    logger.info("   [4G] Stored %s multi-word expressions.", f"{phrase_count:,}")

    # Link example sentences from Tatoeba
    cursor.execute("SELECT id, text_en, cefr_level FROM sentences;")
    sentence_pool = [
        {"id": r[0], "text_en": r[1], "cefr_level": r[2]}
        for r in cursor.fetchall()
    ]
    matcher = PhraseExampleMatcher(sentence_pool)

    cursor.execute("SELECT id, phrase FROM phrases;")
    stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
    link_batch = matcher.match_phrases(stored_phrases)
    for i in range(0, len(link_batch), 5000):
        db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])
    logger.info("   [4G] Linked %s example sentences to phrases.", f"{len(link_batch):,}")

    # Generate TTS audio for all phrases
    async def generate_phrase_audio():
        audio_gen = AudioGenerator()
        for pid, ptext in stored_phrases:
            res = await audio_gen.generate_dual_speed_phrase(pid, ptext)
            status = "ok" if res["standard_path"] and res["fast_path"] else "failed"
            db_manager.update_phrase_audio(
                pid,
                str(res["standard_path"]) if res["standard_path"] else None,
                str(res["fast_path"]) if res["fast_path"] else None,
                status
            )

    try:
        asyncio.run(generate_phrase_audio())
        logger.info("   [4G] Generated phrase audio files.")
    except Exception as e:
        logger.warning("   [4G] Phrase audio generation warning: %s", e)

    return {"phrases": phrase_count, "links": len(link_batch)}
```

- [ ] **Step 4: Wire Step 4G into `run_pipeline()`**

In `main.py`, after the `[4F]` block (after line 365, the `except` that logs the audio warning), insert:

```python
    # 4G. Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs)
    logger.info("   [4G] Building Multi-Word Expression Database...")
    phrase_stats = run_phrase_step(db_manager, args)
    logger.info("   [4G] Completed: %s phrases, %s example sentence links.",
                f"{phrase_stats['phrases']:,}", f"{phrase_stats['links']:,}")
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_phrase_pipeline.py -v`
Expected: both tests PASS

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS — full suite green

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_phrase_pipeline.py
git commit -m "feat(pipeline): Step 4G ingests multi-word expressions with CEFR, examples and audio"
```

---

### Task 9: Documentation update

**Files:**
- Modify: `README.md`
- Modify: `docs/dataset_system_architecture.md`

- [ ] **Step 1: Update README**

In `README.md`, in the project structure tree, change:

```
│   ├── nlp/                 # Lemmatizer, CEFR, Collocations, Reflex Engine
```

to:

```
│   ├── nlp/                 # Lemmatizer, CEFR, Collocations, Reflex, Phrase Engine
```

And in the intro paragraph (line 3), append after "Bài tập phản xạ":

```markdown
, Thành ngữ & Cụm từ cố định (Idioms, Phrasal Verbs, Proverbs)
```

- [ ] **Step 2: Update architecture doc**

In `docs/dataset_system_architecture.md`, find the pipeline steps section and add one line documenting Step 4G (follow the formatting style of the existing steps):

```markdown
## Bước 4G: Multi-Word Expressions (Thành ngữ & Cụm từ cố định)

Quét lại Kaikki dump để trích idioms, phrasal verbs, proverbs và fixed expressions
(bị lọc bỏ ở bước ingestion từ đơn). Mỗi cụm từ được:

- Chấm CEFR theo từ thành phần (`PhraseGrader`, dùng lại `CEFRGrader`)
- Nối 1-5 câu ví dụ Tatoeba ưu tiên câu dễ (`PhraseExampleMatcher`)
- Dịch nghĩa tiếng Việt (Kaikki translations, fallback `Translator`)
- Tạo audio 1.0x/1.2x (`AudioGenerator.generate_dual_speed_phrase`)

Lưu vào bảng `phrases` và `phrase_sentences`, export kèm theo
`english_dataset.db` với index riêng (`idx_phrases_cefr`, `idx_phrases_type`, ...).
```

(Adjust wording/location to match the existing document structure — the key content is the 4G step description and the two new tables.)

- [ ] **Step 3: Verify docs render (no test needed)**

Run: `.venv/bin/pytest tests/test_phrase_pipeline.py -v`
Expected: still PASS (docs change only)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/dataset_system_architecture.md
git commit -m "docs: document Step 4G multi-word expression pipeline"
```

---

### Final verification

- [ ] **Run the full test suite one last time**

Run: `make test`
Expected: ALL PASS

- [ ] **Summarize results to the user** — phrases ingested count (from a `make run` or dry-run log), test counts, and next steps (sub-project B: Lexical Relations & Topics).

---

## Deviation Log

- **Task 5 (2026-08-03):** The plan's test `test_match_phrase_boundary_rejects_partial_word` requires "gave up" (past tense, sentence 5) to match "give up", which literal substring matching cannot do. Implemented inflection tolerance instead: irregular verb map (~90 families) + suffix stemming in `PhraseExampleMatcher`, with the literal boundary-safe matcher kept as fallback. All 5 plan tests pass verbatim; "give upward" still correctly rejected. Known limits: no magic-e stemming ("dancing" vs "dance"); "news"→"new" false positives possible. Optional follow-up: replace hand-rolled stemmer with existing spaCy lemmatizer (`src/nlp/lemmatizer.py`).

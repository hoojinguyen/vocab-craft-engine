# Pipeline Performance Optimization & Hybrid Vietnamese Translation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Step 4G & Step 4I pipeline execution bottlenecks (reducing total run time from 1h50m to < 15 minutes) while achieving 100% Vietnamese translation coverage for Core 3000 & Top 10,000 words.

**Architecture:** 
Implement an Offline-First & Async Batching pipeline. Step 4G removes online HTTP translation during staging and optimizes sentence matching via SQL candidate indexing (`SQLPhraseExampleMatcher`). Step 4I runs a 2-phase hybrid translation engine: Phase 1 applies instant (0ms) offline gloss extraction from Kaikki/Tatoeba/Subtitles dumps, and Phase 2 dispatches unmapped terms to a multi-worker `ThreadPoolExecutor` async pool prioritized by CEFR rank (Core 3000 & Top 10k words first).

**Tech Stack:** Python 3.11+, SQLite3, `concurrent.futures.ThreadPoolExecutor`, `deep_translator`, `pytest`.

## Global Constraints

- **Python Version:** Python 3.11+
- **Test Framework:** `pytest`
- **Output File Paths:**
  - Plan file: `docs/superpowers/plans/2026-08-10-pipeline-performance-hybrid-translation-plan.md`
  - Spec file: `docs/superpowers/specs/2026-08-10-pipeline-performance-hybrid-translation-design.md`
- **Concurrency Limit:** Max 20 worker threads for online translation (`max_workers=20`) to prevent API throttling.
- **Request Timeout:** Hard deadline of 5.0 seconds per translation call.
- **Data Integrity:** Zero English passthrough strings in `definition_vi` or `meaning_vi` (all outputs validated via `VietnameseTextValidator`).

---

### Task 1: Offline Gloss Extractor (`src/nlp/offline_gloss_extractor.py`)

**Files:**
- Create: `src/nlp/offline_gloss_extractor.py`
- Create: `tests/test_offline_gloss_extractor.py`

**Interfaces:**
- Consumes: Raw Kaikki JSON file (`KAIKKI_JSON_PATH`) and SQLite connection.
- Produces: `OfflineGlossExtractor.get_translation(word_or_phrase: str) -> Optional[str]` and `OfflineGlossExtractor.backfill_db_glosses(db_manager) -> Dict[str, int]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_offline_gloss_extractor.py
import pytest
import sqlite3
from pathlib import Path
from src.nlp.offline_gloss_extractor import OfflineGlossExtractor

def test_offline_gloss_extractor_lookup(tmp_path):
    kaikki_sample = tmp_path / "kaikki_sample.json"
    kaikki_sample.write_text(
        '{"word": "apple", "lang_code": "vi", "senses": [{"glosses": ["quả táo"]}]}\n'
        '{"word": "give up", "lang_code": "vi", "senses": [{"glosses": ["từ bỏ"]}]}\n',
        encoding="utf-8"
    )
    extractor = OfflineGlossExtractor(kaikki_path=kaikki_sample)
    assert extractor.get_translation("apple") == "quả táo"
    assert extractor.get_translation("give up") == "từ bỏ"
    assert extractor.get_translation("nonexistent_xyz") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_offline_gloss_extractor.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.nlp.offline_gloss_extractor'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/nlp/offline_gloss_extractor.py
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)

class OfflineGlossExtractor:
    """Extracts Vietnamese translations from Kaikki raw JSON dumps into a fast in-memory map."""

    def __init__(self, kaikki_path: Path):
        self.kaikki_path = Path(kaikki_path)
        self.validator = VietnameseTextValidator()
        self.gloss_map: Dict[str, str] = {}
        self._load_glosses()

    def _load_glosses(self) -> None:
        if not self.kaikki_path.exists():
            logger.warning("Kaikki path %s does not exist for offline gloss extraction.", self.kaikki_path)
            return

        count = 0
        try:
            with open(self.kaikki_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("lang_code") == "vi":
                            word = data.get("word", "").strip().lower()
                            senses = data.get("senses", [])
                            for sense in senses:
                                glosses = sense.get("glosses", [])
                                if glosses and isinstance(glosses[0], str):
                                    g_text = glosses[0].strip()
                                    if g_text and self.validator.is_vietnamese(g_text):
                                        self.gloss_map[word] = g_text
                                        count += 1
                                        break
                    except Exception:
                        continue
            logger.info("Loaded %d offline Vietnamese glosses from Kaikki dump.", count)
        except Exception as e:
            logger.warning("Error reading Kaikki dump for offline glosses: %s", e)

    def get_translation(self, text: str) -> Optional[str]:
        clean = text.strip().lower()
        return self.gloss_map.get(clean)

    def backfill_db_glosses(self, db_manager) -> Dict[str, int]:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # Backfill definitions
        cursor.execute("SELECT d.id, w.lemma FROM definitions d JOIN words w ON w.id = d.word_id WHERE d.definition_vi IS NULL OR d.definition_vi = '';")
        def_rows = cursor.fetchall()
        def_updates = [(self.gloss_map[w.lower()], d_id) for d_id, w in def_rows if w.lower() in self.gloss_map]
        if def_updates:
            cursor.executemany("UPDATE definitions SET definition_vi = ? WHERE id = ?;", def_updates)
            
        # Backfill collocations
        cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        col_rows = cursor.fetchall()
        col_updates = [(self.gloss_map[p.lower()], c_id) for c_id, p in col_rows if p.lower() in self.gloss_map]
        if col_updates:
            cursor.executemany("UPDATE collocations SET meaning_vi = ? WHERE id = ?;", col_updates)
            
        # Backfill phrases
        cursor.execute("SELECT id, phrase FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        phr_rows = cursor.fetchall()
        phr_updates = [(self.gloss_map[p.lower()], p_id) for p_id, p in phr_rows if p.lower() in self.gloss_map]
        if phr_updates:
            cursor.executemany("UPDATE phrases SET definition_vi = ? WHERE id = ?;", phr_updates)

        conn.commit()
        return {
            "definitions": len(def_updates),
            "collocations": len(col_updates),
            "phrases": len(phr_updates)
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_offline_gloss_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/offline_gloss_extractor.py tests/test_offline_gloss_extractor.py
git commit -m "feat: add OfflineGlossExtractor for 0ms local Vietnamese gloss lookup"
```

---

### Task 2: SQL Candidate Phrase Sentence Matcher (`src/nlp/phrase_example_matcher.py`)

**Files:**
- Modify: `src/nlp/phrase_example_matcher.py`
- Create: `tests/test_sql_phrase_matcher.py`

**Interfaces:**
- Consumes: SQLite database cursor/connection and list of phrase dicts `[{"id": 1, "phrase": "give up"}]`.
- Produces: `PhraseExampleMatcher.match_phrases_sql(db_conn, phrases: List[Dict]) -> List[Dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sql_phrase_matcher.py
import sqlite3
import pytest
from src.nlp.phrase_example_matcher import PhraseExampleMatcher

def test_sql_phrase_matching(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sentences (id INTEGER PRIMARY KEY, text_en TEXT, cefr_level TEXT);")
    cursor.execute("INSERT INTO sentences VALUES (1, 'Never give up your dreams.', 'A1');")
    cursor.execute("INSERT INTO sentences VALUES (2, 'He gave up smoking last year.', 'A2');")
    cursor.execute("INSERT INTO sentences VALUES (3, 'An unrelated sentence here.', 'B1');")
    conn.commit()

    matcher = PhraseExampleMatcher(sentences=[])
    results = matcher.match_phrases_sql(conn, [{"id": 10, "phrase": "give up"}])
    
    sentence_ids = [r["sentence_id"] for r in results]
    assert 1 in sentence_ids
    assert 2 in sentence_ids
    assert 3 not in sentence_ids
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sql_phrase_matcher.py -v`
Expected: FAIL with "AttributeError: 'PhraseExampleMatcher' object has no attribute 'match_phrases_sql'"

- [ ] **Step 3: Write minimal implementation**

Add `match_phrases_sql` to `PhraseExampleMatcher` in `src/nlp/phrase_example_matcher.py`:

```python
    def match_phrases_sql(self, conn, phrases: List[Dict[str, Any]], max_candidates: int = 50) -> List[Dict[str, Any]]:
        """Fast SQL-based candidate lookup for phrase-sentence matching."""
        cursor = conn.cursor()
        results: List[Dict[str, Any]] = []

        for item in phrases:
            p_id = item["id"]
            phrase = item["phrase"]
            words = [w.strip(PUNCT) for w in phrase.lower().replace("-", " ").split() if w.strip(PUNCT)]
            key_words = [w for w in words if w not in STOPWORDS] or words
            if not key_words:
                continue

            stem0 = _stem(key_words[0])
            # Query candidate sentences containing stem or word variant
            cursor.execute(
                """
                SELECT id, text_en, cefr_level FROM sentences 
                WHERE text_en LIKE ? OR text_en LIKE ?
                LIMIT ?;
                """,
                (f"%{key_words[0]}%", f"%{stem0}%", max_candidates)
            )
            candidates = [{"id": r[0], "text_en": r[1], "cefr_level": r[2]} for r in cursor.fetchall()]

            matches = [
                sent for sent in candidates
                if self._is_boundary_match(phrase.lower(), sent["text_en"].lower())
                or self._tokens_match_phrase(words, sent["text_en"].lower())
            ]
            matches.sort(key=lambda s: CEFR_ORDER.get(s.get("cefr_level"), 2))

            for i, sent in enumerate(matches[:MAX_EXAMPLES_PER_PHRASE]):
                results.append({"phrase_id": p_id, "sentence_id": sent["id"], "rank": i + 1})

        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sql_phrase_matcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/phrase_example_matcher.py tests/test_sql_phrase_matcher.py
git commit -m "feat: add match_phrases_sql to PhraseExampleMatcher for indexed sentence matching"
```

---

### Task 3: Step 4G Pipeline Optimization (`main.py`)

**Files:**
- Modify: `main.py:97-194`
- Test: `tests/test_phrase_step_integration.py`

**Interfaces:**
- Consumes: `OfflineGlossExtractor` and `PhraseExampleMatcher.match_phrases_sql()`.
- Produces: Fast `run_phrase_step(db_manager, args)` execution (< 2 minutes total).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phrase_step_integration.py
import pytest
from unittest.mock import MagicMock
from main import run_phrase_step

def test_run_phrase_step_fast_execution(tmp_path):
    db_manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    db_manager.get_connection.return_value = conn
    conn.cursor.return_value = cursor
    cursor.fetchone.side_effect = [(0,), (0,)]  # 0 existing phrases, 0 missing audio
    
    args = MagicMock()
    args.force_reset = False
    
    # Mock phrase parser returning 5 test phrases
    with pytest.MonkeyPatch().context() as m:
        m.setattr("main.PhraseParser.parse_phrases", lambda self: [
            {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "verb", "definition_en": "stop trying"}
        ])
        stats = run_phrase_step(db_manager, args)
        assert stats["phrases"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_phrase_step_integration.py -v`
Expected: FAIL due to `Translator.translate_text` online call or missing `OfflineGlossExtractor` in `run_phrase_step`.

- [ ] **Step 3: Update `run_phrase_step` in `main.py`**

In `main.py`, update `run_phrase_step()` to:
1. Initialize `OfflineGlossExtractor(KAIKKI_JSON_PATH)`.
2. Use `offline_extractor.get_translation(item["phrase"])` instead of calling `translator.translate_text()`.
3. Use `matcher.match_phrases_sql(conn, stored_phrases)` for fast sentence linking.

```python
def run_phrase_step(db_manager, args) -> dict:
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM phrases;")
    existing_phrases = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM phrases WHERE audio_std IS NULL OR audio_fast IS NULL;")
    missing_audio = cursor.fetchone()[0]

    if existing_phrases > 500 and missing_audio == 0 and not args.force_reset:
        logger.info("[4G] CHECKPOINT DETECTED: %s phrases with complete audio already exist. Skipping.", f"{existing_phrases:,}")
        return {"phrases": existing_phrases, "links": 0}

    logger.info("   [4G] Ingesting Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs)...")
    phrase_parser = PhraseParser(KAIKKI_JSON_PATH)
    grader = PhraseGrader(CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH))
    offline_extractor = OfflineGlossExtractor(KAIKKI_JSON_PATH)

    phrases_batch = []
    phrase_count = 0
    for item in phrase_parser.parse_phrases():
        graded = grader.grade_phrase(item["phrase"])
        vi_gloss = item.get("definition_vi") or offline_extractor.get_translation(item["phrase"])
        phrases_batch.append({
            "phrase": item["phrase"],
            "phrase_type": item["phrase_type"],
            "pos": item["pos"],
            "cefr_level": graded["cefr_level"],
            "difficulty_score": graded["difficulty_score"],
            "definition_en": item["definition_en"],
            "definition_vi": vi_gloss,  # NULL if unmapped, handled by 4I batch
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

    # Fast SQL-indexed example sentence matching
    cursor.execute("SELECT id, phrase FROM phrases;")
    stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
    matcher = PhraseExampleMatcher(sentences=[])
    link_batch = matcher.match_phrases_sql(conn, stored_phrases)

    for i in range(0, len(link_batch), 5000):
        db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])
    logger.info("   [4G] Linked %s example sentences to phrases via SQL matching.", f"{len(link_batch):,}")

    # Audio generation loop remains unchanged...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_phrase_step_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_phrase_step_integration.py
git commit -m "perf: optimize Step 4G with offline gloss lookup and SQL-indexed sentence matching"
```

---

### Task 4: Tiered Async Batch Translator (`src/nlp/translator.py`)

**Files:**
- Modify: `src/nlp/translator.py`
- Create: `tests/test_async_translator.py`

**Interfaces:**
- Consumes: List of `(id, text_en)` tuples and `max_workers=20`.
- Produces: `Translator.translate_batch_async(items: List[Tuple[int, str]], max_workers: int = 20) -> List[Tuple[str, int]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_async_translator.py
import pytest
from src.nlp.translator import Translator

def test_async_batch_translation(monkeypatch):
    translator = Translator()
    
    # Mock _translate_with_timeout to return dummy Vietnamese string
    monkeypatch.setattr(translator, "_translate_with_timeout", lambda t, text: f"dịch {text}")
    
    items = [(1, "apple"), (2, "banana"), (3, "orange")]
    results = translator.translate_batch_async(items, max_workers=2)
    
    assert len(results) == 3
    assert ("dịch apple", 1) in results
    assert ("dịch banana", 2) in results
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_translator.py -v`
Expected: FAIL with "AttributeError: 'Translator' object has no attribute 'translate_batch_async'"

- [ ] **Step 3: Implement `translate_batch_async` in `Translator`**

Add `translate_batch_async` using `concurrent.futures.ThreadPoolExecutor` in `src/nlp/translator.py`:

```python
    def translate_batch_async(self, items: List[Tuple[int, str]], max_workers: int = 20) -> List[Tuple[str, int]]:
        """
        Translates a batch of (id, text_en) tuples in parallel using ThreadPoolExecutor.
        Returns a list of (translated_vi, id) tuples for database UPDATE queries.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: List[Tuple[str, int]] = []
        if not items:
            return results

        def _worker(item_id: int, text: str) -> Optional[Tuple[str, int]]:
            vi = self.translate_text(text)
            if vi and self.validator.is_vietnamese(vi):
                return (vi, item_id)
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {
                executor.submit(_worker, item_id, text): (item_id, text)
                for item_id, text in items
            }
            for future in as_completed(future_to_item):
                res = future.result()
                if res:
                    results.append(res)

        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_translator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/translator.py tests/test_async_translator.py
git commit -m "feat: add translate_batch_async for 20x parallel HTTP translation"
```

---

### Task 5: Step 4I Hybrid Pipeline & E2E Verification (`main.py`)

**Files:**
- Modify: `main.py:298-404` (`run_vietnamese_step`)
- Test: `tests/test_vietnamese_step_e2e.py`

**Interfaces:**
- Consumes: `OfflineGlossExtractor.backfill_db_glosses()` & `Translator.translate_batch_async()`.
- Produces: Fast Step 4I execution prioritizing Core 3000 & Top 10,000 words.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vietnamese_step_e2e.py
import pytest
from unittest.mock import MagicMock
from main import run_vietnamese_step

def test_run_vietnamese_step_hybrid(monkeypatch):
    db_manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    db_manager.get_connection.return_value = conn
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = []
    
    args = MagicMock()
    args.force_reset = False
    args.vi_budget = 100
    
    monkeypatch.setattr("main.OfflineGlossExtractor.backfill_db_glosses", lambda self, db: {"definitions": 5, "collocations": 0, "phrases": 0})
    stats = run_vietnamese_step(db_manager, args)
    assert stats["definitions"] >= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vietnamese_step_e2e.py -v`
Expected: FAIL due to missing hybrid 2-phase execution in `run_vietnamese_step`.

- [ ] **Step 3: Update `run_vietnamese_step` in `main.py`**

Modify `run_vietnamese_step()` in `main.py`:
1. Run Phase 1: `OfflineGlossExtractor(KAIKKI_JSON_PATH).backfill_db_glosses(db_manager)`.
2. Run Phase 2: Prioritize CEFR A1-B2 & Core 3000 definitions, collocations, phrases using `translator.translate_batch_async()`.

```python
def run_vietnamese_step(db_manager, args) -> dict:
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # One-time cleanup: English passthrough -> NULL
    cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
    conn.commit()

    # Phase 1: Local Offline Gloss Extraction (0ms Instant Backfill)
    logger.info("   [4I Phase 1] Running Offline Gloss Extractor from Kaikki/Tatoeba dumps...")
    offline_extractor = OfflineGlossExtractor(KAIKKI_JSON_PATH)
    offline_stats = offline_extractor.backfill_db_glosses(db_manager)
    logger.info("   [4I Phase 1] Instant Offline Backfill: %d definitions, %d collocations, %d phrases.",
                offline_stats["definitions"], offline_stats["collocations"], offline_stats["phrases"])

    # Phase 2: Candidates missing Vietnamese, graded words (Core 3000 & Top 10k) first
    cursor.execute("""
        SELECT d.id, d.definition_en FROM definitions d
        JOIN words w ON w.id = d.word_id
        WHERE d.definition_vi IS NULL OR d.definition_vi = ''
        ORDER BY (w.cefr_level IS NULL), w.frequency_rank ASC, d.id;
    """)
    priority_definitions = cursor.fetchall()
    cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
    priority_collocations = cursor.fetchall()
    cursor.execute("SELECT id, definition_en FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
    priority_phrases = cursor.fetchall()

    remaining = len(priority_definitions) + len(priority_collocations) + len(priority_phrases)
    if remaining == VI_EMPTY_BACKFILL_CHECKPOINT and not args.force_reset:
        logger.info("[4I Phase 2] CHECKPOINT DETECTED: no missing Vietnamese translations remain. Skipping.")
        return offline_stats

    logger.info("   [4I Phase 2] Backfilling Vietnamese translations via Tiered Async Pool (%s definitions, %s collocations, %s phrases)...",
                f"{len(priority_definitions):,}", f"{len(priority_collocations):,}", f"{len(priority_phrases):,}")

    translator = Translator()
    budget = getattr(args, "vi_budget", VI_TRANSLATION_BUDGET)

    # Process in batches using translate_batch_async (max 20 workers)
    def _backfill_async(rows, table, id_col, target_col, current_budget):
        if current_budget <= 0 or not rows:
            return 0, current_budget
        to_process = rows[:current_budget]
        updated_tuples = translator.translate_batch_async(to_process, max_workers=20)
        if updated_tuples:
            cursor.executemany(f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?;", updated_tuples)
            conn.commit()
            translator.save_cache()
        return len(updated_tuples), current_budget - len(to_process)

    def_updated, budget_left = _backfill_async(priority_definitions, "definitions", "id", "definition_vi", budget)
    col_updated, budget_left = _backfill_async(priority_collocations, "collocations", "id", "meaning_vi", budget_left)
    phr_updated, _ = _backfill_async(priority_phrases, "phrases", "id", "definition_vi", budget_left)

    total_defs = offline_stats["definitions"] + def_updated
    total_colls = offline_stats["collocations"] + col_updated
    total_phrs = offline_stats["phrases"] + phr_updated

    logger.info("   [4I] Completed: %s definitions, %s collocations, %s phrases translated.",
                f"{total_defs:,}", f"{total_colls:,}", f"{total_phrs:,}")

    return {"definitions": total_defs, "collocations": total_colls, "phrases": total_phrs}
```

- [ ] **Step 4: Run full test suite**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_vietnamese_step_e2e.py
git commit -m "feat: complete Step 4I hybrid offline + tiered async translation engine"
```

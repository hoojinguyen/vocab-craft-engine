# Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add synonyms, antonyms, hypernyms, hyponyms, and topic assignments to the English dataset engine by mining the already-present relation/topic fields in the Kaikki dump (currently discarded), with curated theme mapping and inverse rows for hypernym/hyponym.

**Architecture:** Mirrors sub-project A (marker = `run_phrase_step`). A new `RelationParser` streams the Kaikki dump via `KaikkiParser.parse_raw_items()` (filtering to single-word entries), `TopicMapper` maps raw Kaikki topic keys to a curated ~30 theme taxonomy, and a new `run_relations_step()` (Step 4H) inserts relations + topics, links targets to `words.id`, and generates inverse hyponym rows for natural hypernyms. Two new tables (`word_relations`, `word_topics`) follow the established `INSERT OR IGNORE` batch pattern; indexes are duplicated in the exporter.

**Tech Stack:** Python 3, SQLite (via `DatabaseManager`), ijson-free JSONL streaming via existing `KaikkiParser.parse_raw_items()`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-lexical-relations-topics-design.md`

---

## File Structure

- `src/db/staging_db.py` — MODIFY: 2 new tables (`word_relations`, `word_topics`), 4 new indexes, 2 new batch-insert methods
- `src/nlp/topic_mapper.py` — CREATE: pure `TopicMapper` (curated theme map + fallback)
- `src/ingestion/relation_parser.py` — CREATE: `RelationParser` (streams raw items, extracts relations + topics)
- `main.py` — MODIFY: imports, `RELATION_CHECKPOINT`/`TOPIC_CHECKPOINT` constants, `run_relations_step()`, 4H wiring, force-reset drop list
- `src/export/sqlite_exporter.py` — MODIFY: 4 indexes for the 2 new tables
- `tests/test_staging_db.py` — MODIFY: relation tables + idempotency tests
- `tests/test_topic_mapper.py` — CREATE
- `tests/test_relation_parser.py` — CREATE
- `tests/test_relations_pipeline.py` — CREATE: e2e + checkpoint tests
- `tests/test_export.py` — MODIFY: index-recreation test
- `README.md`, `docs/dataset_system_architecture.md` — MODIFY: docs (Task 6)

---

## Task 1: Database schema & batch insert methods

**Files:**
- Modify: `src/db/staging_db.py` (init_schema + new methods near other insert_*_batch)
- Test: `tests/test_staging_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_staging_db.py`:

```python
def test_relation_tables_exist(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"word_relations", "word_topics"}.issubset(tables)


def test_insert_word_relations_batch_and_idempotency(temp_db: DatabaseManager):
    temp_db.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"},
        {"lemma": "animal", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 300, "cefr_level": "A1"},
        {"lemma": "hound", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 8000, "cefr_level": "B2"}
    ])
    dog_id = temp_db.get_word_id_by_lemma("dog")
    animal_id = temp_db.get_word_id_by_lemma("animal")
    hound_id = temp_db.get_word_id_by_lemma("hound")

    relations = [
        {"word_id": dog_id, "relation_type": "synonym", "target_text": "hound",
         "target_word_id": hound_id, "inverted": 0, "source": "synonyms"},
        {"word_id": dog_id, "relation_type": "hypernym", "target_text": "animal",
         "target_word_id": animal_id, "inverted": 0, "source": "hypernyms"},
    ]
    temp_db.insert_word_relations_batch(relations)
    # Idempotency: UNIQUE (word_id, relation_type, target_text) + OR IGNORE
    temp_db.insert_word_relations_batch(relations)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM word_relations;")
    assert cursor.fetchone()[0] == 2


def test_insert_word_topics_batch_and_idempotency(temp_db: DatabaseManager):
    temp_db.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"}
    ])
    dog_id = temp_db.get_word_id_by_lemma("dog")

    topics = [{"word_id": dog_id, "topic": "Nature & Animals", "raw_topic": "zoology"}]
    temp_db.insert_word_topics_batch(topics)
    temp_db.insert_word_topics_batch(topics)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM word_topics;")
    assert cursor.fetchone()[0] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_staging_db.py::test_relation_tables_exist tests/test_staging_db.py::test_insert_word_relations_batch_and_idempotency tests/test_staging_db.py::test_insert_word_topics_batch_and_idempotency -v`
Expected: FAIL (`no such table: word_relations`).

- [ ] **Step 3: Implement the schema + methods**

In `src/db/staging_db.py` `init_schema()`, after the `phrase_sentences` CREATE TABLE block (around line 182) and **before** the `cursor.execute("CREATE UNIQUE INDEX ...")` block (around line 185), add:

```python
        # 12. Word Lexical Relations table (N-1 to words, self-referencing)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                target_text TEXT NOT NULL,
                target_word_id INTEGER,
                inverted INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
                FOREIGN KEY (target_word_id) REFERENCES words (id) ON DELETE CASCADE
            );
        """)

        # 13. Word Topics table (N-1 to words)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_topics (
                word_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                raw_topic TEXT,
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
            );
        """)
```

In the same `init_schema()` index block (after the `idx_phrase_sentences_sentence` line), add:

```python
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);")
```

Add two new methods (place after `insert_phrase_sentences_batch`, mirroring the existing `insert_words_batch`/`insert_phrases_batch` pattern):

```python
    def insert_word_relations_batch(self, relations_data: List[Dict[str, Any]]) -> int:
        """Batch insert lexical relations with IGNORE on duplicate (word_id, relation_type, target_text)."""
        if not relations_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO word_relations (word_id, relation_type, target_text, target_word_id, inverted, source)
            VALUES (:word_id, :relation_type, :target_text, :target_word_id, :inverted, :source);
        """
        cursor = conn.cursor()
        cursor.executemany(query, relations_data)
        conn.commit()
        return cursor.rowcount

    def insert_word_topics_batch(self, topics_data: List[Dict[str, Any]]) -> int:
        """Batch insert topics with IGNORE on duplicate (word_id, topic)."""
        if not topics_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic)
            VALUES (:word_id, :topic, :raw_topic);
        """
        cursor = conn.cursor()
        cursor.executemany(query, topics_data)
        conn.commit()
        return cursor.rowcount
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_staging_db.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: 45 passed (42 prior + 3 new; note `test_init_schema_creates_tables_and_indexes`, `test_foreign_key_check`, `test_insert_phrase_sentences_...` etc all still green).

- [ ] **Step 6: Commit**

```bash
git add src/db/staging_db.py tests/test_staging_db.py
git commit -m "feat(db): add word_relations and word_topics tables with batch inserts"
```

---

## Task 2: TopicMapper

**Files:**
- Create: `src/nlp/topic_mapper.py`
- Test: `tests/test_topic_mapper.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topic_mapper.py`:

```python
"""
Unit tests for TopicMapper in src.nlp.topic_mapper
"""

from src.nlp.topic_mapper import TopicMapper


def test_map_known_topics():
    assert TopicMapper.map_topic("computing") == "Technology"
    assert TopicMapper.map_topic("medicine") == "Health & Medicine"
    assert TopicMapper.map_topic("zoology") == "Nature & Animals"
    assert TopicMapper.map_topic("milky way") == "Milky Way"  # covered by fallback


def test_map_topic_is_case_and_whitespace_insensitive():
    assert TopicMapper.map_topic("  Medicine  ") == "Health & Medicine"


def test_map_fallback_normalizes_unmapped_topic():
    assert TopicMapper.map_topic("natural-sciences") == "Natural Sciences"
    assert TopicMapper.map_topic("cooking") == "Food & Drink"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_topic_mapper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.nlp.topic_mapper'`.

- [ ] **Step 3: Implement TopicMapper**

Create `src/nlp/topic_mapper.py`:

```python
"""Topic Mapper for English Dataset System Engine.

Maps raw Kaikki topic keys (e.g. "computing") to a curated,
learner-friendly theme taxonomy. Falls back to a normalized raw title
for topics not present in the map.
"""

from typing import Dict

# Curated themes, keyed by raw Kaikki topic key (lowercase).
THEME_MAP: Dict[str, str] = {
    # Technology
    "computing": "Technology",
    "software": "Technology",
    "internet": "Technology",
    "electronics": "Technology",
    "computer": "Technology",
    "programming": "Technology",
    "telecommunications": "Technology",
    "networking": "Technology",
    "artificial intelligence": "Technology",
    # Health & Medicine
    "medicine": "Health & Medicine",
    "medical": "Health & Medicine",
    "anatomy": "Health & Medicine",
    "pharmacology": "Health & Medicine",
    "pharmacy": "Health & Medicine",
    "nutrition": "Health & Medicine",
    "psychiatry": "Health & Medicine",
    "psychology": "Health & Medicine",
    "diseases": "Health & Medicine",
    # Business & Finance
    "money": "Business & Finance",
    "finance": "Business & Finance",
    "business": "Business & Finance",
    "economics": "Business & Finance",
    "economy": "Business & Finance",
    "commerce": "Business & Finance",
    "accounting": "Business & Finance",
    "taxation": "Business & Finance",
    "marketing": "Business & Finance",
    # Law & Government
    "law": "Law & Government",
    "legal": "Law & Government",
    "government": "Law & Government",
    "politics": "Law & Government",
    "military": "Law & Government",
    "crime": "Law & Government",
    "police": "Law & Government",
    # Travel & Transportation
    "travel": "Travel & Transportation",
    "tourism": "Travel & Transportation",
    "shipping": "Travel & Transportation",
    "aeronautics": "Travel & Transportation",
    "aviation": "Travel & Transportation",
    "rail transport": "Travel & Transportation",
    "automotive": "Travel & Transportation",
    # Food & Drink
    "food": "Food & Drink",
    "cooking": "Food & Drink",
    "cuisine": "Food & Drink",
    "culinary": "Food & Drink",
    "gastronomy": "Food & Drink",
    "beverages": "Food & Drink",
    "alcoholic beverages": "Food & Drink",
    # Education & Language
    "education": "Education & Language",
    "linguistics": "Education & Language",
    "grammar": "Education & Language",
    "phonetics": "Education & Language",
    "phonology": "Education & Language",
    # Arts & Entertainment
    "art": "Arts & Entertainment",
    "arts": "Arts & Entertainment",
    "music": "Arts & Entertainment",
    "film": "Arts & Entertainment",
    "fiction": "Arts & Entertainment",
    "literature": "Arts & Entertainment",
    "literary": "Arts & Entertainment",
    "theatre": "Arts & Entertainment",
    "dance": "Arts & Entertainment",
    "photography": "Arts & Entertainment",
    "painting": "Arts & Entertainment",
    "gaming": "Arts & Entertainment",
    # Nature & Animals
    "zoology": "Nature & Animals",
    "botany": "Nature & Animals",
    "ornithology": "Nature & Animals",
    "entomology": "Nature & Animals",
    "ichthyology": "Nature & Animals",
    "mammals": "Nature & Animals",
    "ecology": "Nature & Animals",
    # Science & Mathematics
    "mathematics": "Science & Mathematics",
    "math": "Science & Mathematics",
    "physics": "Science & Mathematics",
    "chemistry": "Science & Mathematics",
    "biology": "Science & Mathematics",
    "astronomy": "Science & Mathematics",
    "geology": "Science & Mathematics",
    # Sports & Fitness
    "sports": "Sports & Fitness",
    "athletics": "Sports & Fitness",
    "boxing": "Sports & Fitness",
    "football": "Sports & Fitness",
    "soccer": "Sports & Fitness",
    "cricket": "Sports & Fitness",
    "tennis": "Sports & Fitness",
    "golf": "Sports & Fitness",
    # Communication & Media
    "media": "Communication & Media",
    "journalism": "Communication & Media",
    "press": "Communication & Media",
    "publishing": "Communication & Media",
    "advertising": "Communication & Media",
    # Religion, Spirituality & Culture
    "religion": "Religion & Culture",
    "religious": "Religion & Culture",
    "christianity": "Religion & Culture",
    "islam": "Religion & Culture",
    "buddhism": "Religion & Culture",
    "hinduism": "Religion & Culture",
    "judaism": "Religion & Culture",
    "mythology": "Religion & Culture",
    "culture": "Religion & Culture",
    "history": "Religion & Culture",
    "archaeology": "Religion & Culture",
    # Home & Family
    "family": "Home & Family",
    "furniture": "Home & Family",
    "household": "Home & Family",
    "textiles": "Home & Family",
    # Emotions & Personality
    "emotions": "Emotions & Personality",
    "personality": "Emotions & Personality",
    # Fashion & Clothing
    "clothing": "Fashion & Clothing",
    "fashion": "Fashion & Clothing",
    # Geography & Environment
    "geography": "Geography & Environment",
    "environment": "Geography & Environment",
    # Weather
    "weather": "Weather & Climate",
    "climate": "Weather & Climate",
    "meteorology": "Weather & Climate",
}


class TopicMapper:
    """Maps raw Kaikki topic keys to curated themes."""

    @staticmethod
    def map_topic(raw: str) -> str:
        key = raw.strip().lower()
        theme = TopicMapper.THEME_MAP.get(key)
        if theme:
            return theme
        return key.replace("-", " ").title()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_topic_mapper.py -v`
Expected: ALL PASS. (`milky way` → fallback `Milky Way`; `cooking` → known map `Food & Drink`.)

- [ ] **Step 5: Commit**

```bash
git add src/nlp/topic_mapper.py tests/test_topic_mapper.py
git commit -m "feat(nlp): curated topic taxonomy mapper with raw fallback"
```

---

## Task 3: RelationParser

**Files:**
- Create: `src/ingestion/relation_parser.py`
- Test: `tests/test_relation_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_relation_parser.py`:

```python
"""
Tests for RelationParser in src.ingestion.relation_parser
"""

import json
import pytest
from pathlib import Path
from src.ingestion.relation_parser import RelationParser


def test_extract_relations_dedupe_and_filter():
    entry = {
        "word": "Dog",
        "pos": "noun",
        "senses": [{"glosses": ["An animal."], "topics": ["zoology", "zoology"]}],
        "synonyms": [{"word": "hound"}, {"word": "1.5"}],
        "hypernyms": [{"word": "animal"}, {"word": "animal"}],
        "antonyms": [{"word": "cat"}]
    }
    parsed = RelationParser.extract_entry_fields(entry)

    assert parsed["word"] == "dog"
    rel_types = {(r["relation_type"], r["target"]) for r in parsed["relations"]}
    assert ("synonym", "hound") in rel_types
    assert ("hypernym", "animal") in rel_types
    assert ("antonym", "cat") in rel_types
    # Bad target (digit) rejected
    assert not any(r["target"] == "1.5" for r in parsed["relations"])
    # Dedupe across senses: "animal" appears once
    assert sum(1 for r in parsed["relations"] if r["target"] == "animal") == 1
    # Topics mapped + deduped
    assert parsed["topics"] == [{"topic": "Nature & Animals", "raw_topic": "zoology"}]


def test_extract_self_reference_dropped():
    parsed = RelationParser.extract_entry_fields({
        "word": "dog",
        "pos": "noun",
        "senses": [],
        "synonyms": [{"word": "dog"}]
    })
    assert parsed is None  # relation dropped, no topics → nothing yielded


def test_extract_rejects_multi_word_entry():
    parsed = RelationParser.extract_entry_fields({
        "word": "break a leg",
        "pos": "idiom",
        "senses": [],
        "synonyms": []
    })
    assert parsed is None


def test_extract_caps_targets_per_type():
    entry = {
        "word": "dog",
        "pos": "noun",
        "senses": [],
        "synonyms": [{"word": f"synonym{i}"} for i in range(30)]
    }
    parsed = RelationParser.extract_entry_fields(entry)
    synonyms = [r for r in parsed["relations"] if r["relation_type"] == "synonym"]
    assert len(synonyms) == 25


def test_parse_entries_streams_only_yielding_entries(tmp_path: Path):
    file = tmp_path / "kaikki.jsonl"
    file.write_text("\n".join(json.dumps(e) for e in [
        {"word": "dog", "pos": "noun", "senses": [{"topics": ["zoology"]}],
         "synonyms": [{"word": "hound"}]},
        {"word": "run", "pos": "noun", "senses": [], "synonyms": []},
        {"word": "cat", "pos": "noun", "senses": [], "antonyms": [{"word": "dog"}]}
    ]), encoding="utf-8")

    rows = list(RelationParser(file).parse_entries())
    assert [r["word"] for r in rows] == ["dog", "cat"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_relation_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ingestion.relation_parser'`.

- [ ] **Step 3: Implement RelationParser**

Create `src/ingestion/relation_parser.py`:

```python
"""
Lexical Relation & Topic Parser for English Dataset System Engine.
Extracts synonyms, antonyms, hypernyms, hyponyms and sense-level topics
from raw Kaikki dump entries (single-word entries only).
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List, Set

from src.ingestion.kaikki_parser import KaikkiParser
from src.nlp.topic_mapper import TopicMapper

logger = logging.getLogger(__name__)

# Only letters, spaces, hyphens, apostrophes and periods are allowed
CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")

MAX_TARGETS_PER_RELATION = 25


class RelationParser:
    """Parses lexical relations and topics from Kaikki dump entries (streaming)."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    @staticmethod
    def extract_entry_fields(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        word = item.get("word", "").strip().lower()
        if not word or " " in word:
            return None

        relations: List[Dict[str, str]] = []
        seen: Set[tuple] = set()
        for section, rel_type in (("synonyms", "synonym"), ("antonyms", "antonym"),
                                  ("hypernyms", "hypernym"), ("hyponyms", "hyponym")):
            candidates = list(item.get(section, []) or [])
            for sense in item.get("senses", []) or []:
                candidates.extend(sense.get(section, []) or [])
            count_for_type = 0
            for rel in candidates:
                if count_for_type >= MAX_TARGETS_PER_RELATION:
                    break
                if not isinstance(rel, dict):
                    continue
                target = (rel.get("word") or "").strip().lower()
                if not target or target == word:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue
                key = (rel_type, target)
                if key in seen:
                    continue
                seen.add(key)
                relations.append({"relation_type": rel_type, "target": target, "source": section})
                count_for_type += 1

        topics: List[Dict[str, str]] = []
        seen_topics: Set[str] = set()
        for sense in item.get("senses", []) or []:
            for raw in sense.get("topics", []) or []:
                raw_label = (raw or "").strip()
                if not raw_label:
                    continue
                key = raw_label.lower()
                if key in seen_topics:
                    continue
                seen_topics.add(key)
                topics.append({"topic": TopicMapper.map_topic(raw_label), "raw_topic": raw_label})

        if not relations and not topics:
            return None
        return {"word": word, "relations": relations, "topics": topics}

    def parse_entries(self) -> Iterator[Dict[str, Any]]:
        """Yields parsed single-word entry dicts: {word, relations, topics}."""
        kaikki = KaikkiParser(self.file_path)
        for item in kaikki.parse_raw_items():
            parsed = self.extract_entry_fields(item)
            if parsed:
                yield parsed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_relation_parser.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/relation_parser.py tests/test_relation_parser.py
git commit -m "feat(ingestion): RelationParser extracts synonyms, antonyms, hypernyms, hyponyms and topics"
```

---

## Task 4: `run_relations_step` + main.py wiring (Step 4H)

**Files:**
- Modify: `main.py` (imports, constants, function, wiring, force-reset drop list)
- Test: `tests/test_relations_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_relations_pipeline.py`:

```python
"""
End-to-end tests for the Step 4H lexical relations & topics pipeline stage.
"""

import json
import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def relation_environment(tmp_path: Path, monkeypatch):
    kaikki_file = tmp_path / "kaikki.jsonl"
    entries = [
        {"word": "dog", "pos": "noun",
         "senses": [{"glosses": ["An animal."], "topics": ["zoology"]}],
         "synonyms": [{"word": "hound"}, {"word": "give up the ghost"}],
         "hypernyms": [{"word": "animal"}]},
        {"word": "animal", "pos": "noun",
         "senses": [{"glosses": ["A living creature."], "topics": ["zoology"]}]},
        {"word": "quick", "pos": "adjective",
         "senses": [{"glosses": ["Fast."]}],
         "antonyms": [{"word": "slow"}]}
    ]
    kaikki_file.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    monkeypatch.setattr(main_module, "KAIKKI_JSON_PATH", kaikki_file)

    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    db_manager.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"},
        {"lemma": "animal", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 300, "cefr_level": "A1"},
        {"lemma": "quick", "pos": "adjective", "ipa_uk": None, "ipa_us": None, "frequency_rank": 900, "cefr_level": "A2"},
        {"lemma": "slow", "pos": "adjective", "ipa_uk": None, "ipa_us": None, "frequency_rank": 1100, "cefr_level": "A2"},
        {"lemma": "hound", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 8000, "cefr_level": "B2"}
    ])
    yield db_manager
    db_manager.close()


def test_run_relations_step_populates_db(relation_environment):
    db_manager = relation_environment
    args = argparse.Namespace(force_reset=False)

    stats = main_module.run_relations_step(db_manager, args)
    assert stats["relations"] > 0
    assert stats["topics"] > 0

    conn = db_manager.get_connection()
    cursor = conn.cursor()

    dog_id = db_manager.get_word_id_by_lemma("dog")
    animal_id = db_manager.get_word_id_by_lemma("animal")
    hound_id = db_manager.get_word_id_by_lemma("hound")
    quick_id = db_manager.get_word_id_by_lemma("quick")
    slow_id = db_manager.get_word_id_by_lemma("slow")

    # Primary relations from the dog entry
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ? ORDER BY relation_type, target_text;", (dog_id,))
    rows = cursor.fetchall()
    assert ("hypernym", "animal", animal_id, 0) in rows
    assert ("synonym", "give up the ghost", None, 0) in rows  # multi-word, unlinked
    assert ("synonym", "hound", hound_id, 0) in rows

    # Inverse row: natural hypernym (dog -> animal) generates hyponym (animal -> dog), inverted=1
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ? AND relation_type = 'hyponym';", (animal_id,))
    inv = cursor.fetchall()
    assert ("hyponym", "dog", dog_id, 1) in inv

    # Antonyms linked (quick -> slow)
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ?;", (quick_id,))
    assert ("antonym", "slow", slow_id, 0) in cursor.fetchall()

    # Topics mapped
    cursor.execute("SELECT topic, raw_topic FROM word_topics WHERE word_id = ?;", (dog_id,))
    assert ("Nature & Animals", "zoology") in cursor.fetchall()


def test_run_relations_step_checkpoint_skips(relation_environment, monkeypatch):
    db_manager = relation_environment
    args = argparse.Namespace(force_reset=False)

    monkeypatch.setattr(main_module, "RELATION_CHECKPOINT", 10)
    monkeypatch.setattr(main_module, "TOPIC_CHECKPOINT", 10)

    dog_id = db_manager.get_word_id_by_lemma("dog")
    db_manager.insert_word_relations_batch([
        {"word_id": dog_id, "relation_type": "synonym", "target_text": f"seed{i}",
         "target_word_id": None, "inverted": 0, "source": "synonyms"}
        for i in range(12)
    ])
    db_manager.insert_word_topics_batch([
        {"word_id": dog_id, "topic": f"Seed{i}", "raw_topic": "seed"} for i in range(12)
    ])

    with patch.object(main_module, "RelationParser") as mock_parser:
        stats = main_module.run_relations_step(db_manager, args)
        mock_parser.assert_not_called()

    assert stats["relations"] == 12
    assert stats["links"] == 0
    assert stats["topics"] == 12
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_relations_pipeline.py -v`
Expected: FAIL with `AttributeError: module 'main' has no attribute 'run_relations_step'`.

- [ ] **Step 3: Add imports, constants and `run_relations_step` in main.py**

Add an import after `from src.nlp.phrase_example_matcher import PhraseExampleMatcher` (line 37):

```python
from src.ingestion.relation_parser import RelationParser
```

Add two module constants near the top (after the imports, before `logging.basicConfig`):

```python
RELATION_CHECKPOINT = 50_000
TOPIC_CHECKPOINT = 1_000
```

Add the step function (place it after `run_phrase_step`, before `run_pipeline`):

```python
def run_relations_step(db_manager, args) -> dict:
    """
    Step 4H: Ingest lexical relations (synonyms, antonyms, hypernyms,
    hyponyms) and topics from the Kaikki dump for single-word entries.
    Checkpoint: skips when > RELATION_CHECKPOINT relations AND
    > TOPIC_CHECKPOINT topic rows already exist.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM word_relations;")
    existing_relations = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM word_topics;")
    existing_topics = cursor.fetchone()[0]

    if existing_relations > RELATION_CHECKPOINT and existing_topics > TOPIC_CHECKPOINT and not args.force_reset:
        logger.info("[4H] CHECKPOINT DETECTED: %s relations, %s topics already exist. Skipping.", f"{existing_relations:,}", f"{existing_topics:,}")
        return {"relations": existing_relations, "links": 0, "topics": existing_topics}

    logger.info("   [4H] Building Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics)...")
    relation_parser = RelationParser(KAIKKI_JSON_PATH)

    # Lemma -> id map so relation targets can be linked back to the words table
    cursor.execute("SELECT id, lemma FROM words;")
    lemma_map = {lemma: word_id for word_id, lemma in cursor.fetchall()}

    relations_batch = []
    topics_batch = []
    relation_count = 0
    topics_count = 0

    for item in relation_parser.parse_entries():
        word_id = lemma_map.get(item["word"])
        if word_id is None:
            continue
        for rel in item["relations"]:
            relations_batch.append({
                "word_id": word_id,
                "relation_type": rel["relation_type"],
                "target_text": rel["target"],
                "target_word_id": lemma_map.get(rel["target"]),
                "inverted": 0,
                "source": rel["source"]
            })
            if len(relations_batch) >= 1000:
                db_manager.insert_word_relations_batch(relations_batch)
                relation_count += len(relations_batch)
                relations_batch = []
                logger.info("   -> Staged %s relations...", f"{relation_count:,}")
        for top in item["topics"]:
            topics_batch.append({"word_id": word_id, "topic": top["topic"], "raw_topic": top["raw_topic"]})
            if len(topics_batch) >= 1000:
                db_manager.insert_word_topics_batch(topics_batch)
                topics_count += len(topics_batch)
                topics_batch = []

    if relations_batch:
        db_manager.insert_word_relations_batch(relations_batch)
        relation_count += len(relations_batch)
    if topics_batch:
        db_manager.insert_word_topics_batch(topics_batch)
        topics_count += len(topics_batch)
    logger.info("   [4H] Stored %s relations and %s topic assignments.", f"{relation_count:,}", f"{topics_count:,}")

    # Inverse pass: each natural hypernym (A -> B) generates hyponym (B -> A), inverted=1
    cursor.execute("""
        SELECT wr.word_id, w.lemma, wr.target_word_id, wr.source
        FROM word_relations wr
        JOIN words w ON w.id = wr.word_id
        WHERE wr.relation_type = 'hypernym' AND wr.inverted = 0 AND wr.target_word_id IS NOT NULL;
    """)
    natural_hypernyms = cursor.fetchall()

    inverse_batch = []
    link_count = 0
    for word_id, lemma, target_word_id, source in natural_hypernyms:
        inverse_batch.append({
            "word_id": target_word_id,
            "relation_type": "hyponym",
            "target_text": lemma,
            "target_word_id": word_id,
            "inverted": 1,
            "source": source
        })
        if len(inverse_batch) >= 5000:
            db_manager.insert_word_relations_batch(inverse_batch)
            link_count += len(inverse_batch)
            inverse_batch = []
    if inverse_batch:
        db_manager.insert_word_relations_batch(inverse_batch)
        link_count += len(inverse_batch)
    logger.info("   [4H] Generated %s inverse hyponym links.", f"{link_count:,}")

    return {"relations": relation_count, "links": link_count, "topics": topics_count}
```

- [ ] **Step 4: Wire Step 4H into `run_pipeline`**

After the 4G block in `run_pipeline` (after line 473, the `logger.info("   [4G] Completed: ...")` block), insert:

```python
    # 4H. Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics)
    logger.info("   [4H] Building Lexical Relations & Topics Database...")
    relation_stats = run_relations_step(db_manager, args)
    logger.info("   [4H] Completed: %s relations, %s inverse links, %s topic assignments.",
                f"{relation_stats['relations']:,}", f"{relation_stats['links']:,}", f"{relation_stats['topics']:,}")
```

- [ ] **Step 5: Add the 2 new tables to the `--force-reset` drop list**

In `run_pipeline`, in the `tables_to_drop` list (currently `["word_sentence_map", "reflex_drills", ...]`, lines 175-179), add `"word_relations", "word_topics"` right after `"word_sentence_map"`:

```python
        tables_to_drop = [
            "word_relations", "word_topics", "word_sentence_map", "reflex_drills", "dialogue_nodes",
            "dialogue_trees", "sentences", "sentence_patterns",
            "collocations", "definitions", "words"
        ]
```

(**Deviation note:** `phrases`/`phrase_sentences` are already missing from this pre-existing drop list — out of scope here, but the 2 new tables MUST be added or a `--force-reset` rebuild leaves orphan FK rows that fail `verify_foreign_keys`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_relations_pipeline.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: 55 passed (45 after Task 1, +3 topic mapper, +5 relation parser, +2 pipeline).

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_relations_pipeline.py
git commit -m "feat(pipeline): Step 4H ingests lexical relations and topics with inverse links"
```

---

## Task 5: Exporter indexes

**Files:**
- Modify: `src/export/sqlite_exporter.py` (optimize_and_package index block, after line 46)
- Test: `tests/test_export.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export.py`:

```python
def test_exporter_creates_relation_indexes(populated_db: Path):
    db_manager = DatabaseManager(db_path=populated_db)
    db_manager.init_schema()

    run_id = db_manager.get_word_id_by_lemma("run")
    jump_id = db_manager.get_word_id_by_lemma("jump")
    db_manager.insert_word_relations_batch([
        {"word_id": run_id, "relation_type": "synonym", "target_text": "jump",
         "target_word_id": jump_id, "inverted": 0, "source": "synonyms"}
    ])
    db_manager.insert_word_topics_batch([
        {"word_id": run_id, "topic": "Technology", "raw_topic": "computing"}
    ])

    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP INDEX IF EXISTS idx_word_relations_unique;")
    cursor.execute("DROP INDEX IF EXISTS idx_word_relations_target;")
    cursor.execute("DROP INDEX IF EXISTS idx_word_topics_unique;")
    cursor.execute("DROP INDEX IF EXISTS idx_word_topics_topic;")
    conn.commit()
    db_manager.close()

    exporter = SQLiteExporter(db_path=populated_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(populated_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN ('word_relations', 'word_topics');")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_word_relations_unique" in indexes
    assert "idx_word_relations_target" in indexes
    assert "idx_word_topics_unique" in indexes
    assert "idx_word_topics_topic" in indexes
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_export.py::test_exporter_creates_relation_indexes -v`
Expected: FAIL (indexes absent after re-optimize).

- [ ] **Step 3: Add the indexes to `optimize_and_package`**

In `src/export/sqlite_exporter.py`, inside the index-building block (after line 46, `idx_phrase_sentences_sentence`), add:

```python
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/pytest -q`
Expected: PASS.
Commit:

```bash
git add src/export/sqlite_exporter.py tests/test_export.py
git commit -m "feat(export): package lexical relation and topic indexes"
```

---

## Task 6: Documentation

**Files:**
- Modify: `README.md`, `docs/dataset_system_architecture.md`

- [ ] **Step 1: README intro + project tree**

In `README.md`:
- In the intro paragraph (line 3), after the existing "Thành ngữ & Cụm từ cố định (Idioms, Phrasal Verbs, Proverbs)" item, add: `lexical relations & topics (Synonyms, Antonyms, Hypernyms, Hyponyms, and 30 curated themes)`.
- In the project tree, the `nlp/` directory line currently ends `...reflex, phrase engine` — extend it to `...reflex, phrase engine, relation & topic engine`.

- [ ] **Step 2: Architecture doc — Step 4H + ER diagram + table definitions**

In `docs/dataset_system_architecture.md`:

1. Add a `### Step 4H: Lexical Relations & Topics` subsection under Section 3, immediately after the Step 4G subsection. Match the Step 4G style (heading + bullets):

```markdown
### Step 4H: Lexical Relations & Topics

Re-scans the Kaikki dump a third time for single-word entries, mapping every word to:

- Its **synonyms, antonyms, hypernyms, and hyponyms** (from entry-level and sense-level relation sections, capped at 25 targets per relation type per word).
- Every hypernym `(A -> B)` also generates an **inverse hyponym** `(B -> A, inverted=1)` so the taxonomy is navigable in both directions.
- **Topic categories** from each sense's `topics` field, mapped through a curated ~30-theme taxonomy (e.g. `computing` -> `Technology`) with a normalized raw fallback.

Persisted in `word_relations` (target text plus an optional link to `words.id`) and `word_topics`, both with UNIQUE indexes for idempotent re-runs. Checkpointed at 50,000 relations / 1,000 topics; a self-healing re-run fills in any gap.
```

2. In the mermaid ER diagram entity list, add two entities consistent with the existing `PHRASES ||--o{ PHRASE_SENTENCES` style:

```mermaid
WORDS ||--o{ WORD_RELATIONS : relates_to
WORDS ||--o{ WORD_TOPICS : tagged_with
```

3. In Section "Table Definitions", append entries `10` and `11` (numbered after the existing 8–9 phrase entries) mirroring the schema at `staging_db.py`:

```markdown
10. **`word_relations`** — id (PK), word_id (FK->words.id), relation_type (synonym/antonym/hypernym/hyponym), target_text, target_word_id (FK->words.id, nullable), inverted (0/1), source. UNIQUE (word_id, relation_type, target_text); index on target_word_id.
11. **`word_topics`** — word_id (FK->words.id), topic, raw_topic. UNIQUE (word_id, topic); index on topic.
```

- [ ] **Step 3: Sanity-check and commit**

```bash
git diff --stat
.venv/bin/pytest -q   # still green
git add README.md docs/dataset_system_architecture.md
git commit -m "docs: Step 4H lexical relations and topics pipeline documentation"
```

---

## Post-Agenda Verification

- [ ] Run: `.venv/bin/pytest -q` → all pass
- [ ] Run: `make test` → all pass
- [ ] `git log --oneline` shows 6 commits on top of `main`

## Deviation Log

| # | Plan | Implementation | Reason |
|---|---|---|---|
| 1 | (plan addition) | `word_relations` & `word_topics` added to the `--force-reset` drop list | Without this, a forced rebuild orphans existing relation rows → `verify_foreign_keys` fails. Pre-existing `phrases`/`phrase_sentences` omission untouched (out of scope). |
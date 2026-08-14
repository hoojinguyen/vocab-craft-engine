# Pipeline V2 Phase 2 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement robust, high-quality NLP transforms (Sentence Linking, Phrase Extraction, Relation Deduplication, Topic Mapping) and enrichment generators (Hybrid Batch Translation, Reflex Drills, Dialogue Scenarios, Audio Generation) replacing all placeholder stubs with verified, production-grade linguistic pipelines.

**Architecture:** 
- Transforms operate on DuckDB staging tables using vectorized batch operations, spaCy/lemmatization token matching, and `theme_map.yaml` taxonomy.
- Enrichment pipelines use batch cache lookups (`_translation_cache`), multi-threaded/offline Argos translation with bulk table updates, CEFR-graded dynamic distractors for reflex drills, and structured branching dialogue graphs.

**Tech Stack:** Python 3.11+, DuckDB, spaCy, orjson, PyYAML, argostranslate, deep-translator, edge-tts, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-pipeline-v2-remediation-spec.md`

## Global Constraints
- All transforms must complete in **< 15 minutes** combined on full datasets.
- No dummy/mock hardcoded placeholders (e.g. no 5-phrasal-verb lists, no static `["walk", "jump", "fly"]` distractors).
- Zero memory blowouts: all sentence and phrase linkers must process in streaming batches (<= 10,000 items per batch).
- Translation must never block or hang on row-by-row synchronous HTTP calls; use batch cache lookups and bulk `UPDATE` via temporary staging tables.
- Foreign key integrity must be maintained across `word_sentences`, `phrase_sentences`, `word_relations`, `word_topics`, `reflex_drills`, and `dialogue_nodes`.
- 100% test pass rate with TDD (Test-Driven Development).

---

### Task 1: High-Performance Sentence Linker with Lemmatization

**Files:**
- Modify: `src/transform/sentence_linker.py`
- Test: `tests/test_transform/test_sentence_linker.py`

**Interfaces:**
- Consumes: `words` (id, lemma), `sentences` (id, text_en) from DuckDB staging
- Produces: `word_sentences` (word_id, sentence_id) mapping table populated with token & lemma matches.

- [ ] **Step 1: Write test for Sentence Linker lemmatization and batch linking**

```python
# tests/test_transform/test_sentence_linker.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.sentence_linker import SentenceLinker

def test_sentence_linker_lemmatized_matching(tmp_path: Path):
    db_file = tmp_path / "link_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    # Pre-populate sample words
    mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "dog", "pos": "noun", "source": "kaikki"},
        {"lemma": "fast", "pos": "adj", "source": "kaikki"},
    ])

    # Pre-populate sample sentences (including inflected forms 'running', 'dogs')
    mgr.insert_batch_fast("sentences", [
        {"text_en": "The dogs are running very fast in the park.", "text_vi": "Những con chó đang chạy rất nhanh trong công viên.", "source": "tatoeba"},
        {"text_en": "He runs every morning.", "text_vi": "Anh ấy chạy mỗi sáng.", "source": "tatoeba"},
    ])

    linker = SentenceLinker()
    linked_count = linker.link(mgr, batch_size=1000)
    assert linked_count > 0

    conn = mgr.get_connection()
    # Check that 'dog' and 'run' were linked to sentence 1 even if sentence has 'dogs' and 'running'
    links = conn.execute("""
        SELECT w.lemma, s.text_en 
        FROM word_sentences ws
        JOIN words w ON ws.word_id = w.id
        JOIN sentences s ON ws.sentence_id = s.id
        ORDER BY w.lemma, s.id
    """).fetchall()

    lemmas_linked = {row[0] for row in links}
    assert "run" in lemmas_linked
    assert "fast" in lemmas_linked
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_sentence_linker.py -v`

- [ ] **Step 3: Implement streaming batch `SentenceLinker`**

Modify `src/transform/sentence_linker.py`:
- Load dictionary of lemma/word lookup from DuckDB `words`.
- Process `sentences` in streaming batches of 5,000 using cursor fetchmany.
- Tokenize and clean punctuation for each sentence, mapping exact tokens and basic regular inflections (e.g. `-s`, `-ed`, `-ing`, irregular forms) to `word_id`.
- Insert into `word_sentences` using `db_mgr.insert_batch_fast` in streaming chunks.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_sentence_linker.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/transform/sentence_linker.py tests/test_transform/test_sentence_linker.py
git commit -m "feat(transform): implement high-speed streaming sentence linker with inflection matching"
```

---

### Task 2: Phrase & Multi-Word Expression Extractor

**Files:**
- Modify: `src/transform/phrase_extractor.py`
- Test: `tests/test_transform/test_phrase_extractor.py`

**Interfaces:**
- Consumes: `words`, `sentences`, `definitions` from DuckDB
- Produces: `phrases` (phrase, phrase_type, pos, cefr_level, definition_en), `phrase_sentences` (phrase_id, sentence_id, rank).

- [ ] **Step 1: Write test for Phrase & MWE Extractor**

```python
# tests/test_transform/test_phrase_extractor.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.phrase_extractor import PhraseExtractor

def test_phrase_extractor_categorization_and_linking(tmp_path: Path):
    db_file = tmp_path / "phrase_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    mgr.insert_batch_fast("sentences", [
        {"text_en": "You should never give up on your dreams.", "text_vi": "Bạn không bao giờ nên từ bỏ ước mơ của mình.", "source": "tatoeba"},
        {"text_en": "Good luck tonight, break a leg!", "text_vi": "Chúc may mắn tối nay, diễn tốt nhé!", "source": "tatoeba"},
        {"text_en": "Better late than never is an old proverb.", "text_vi": "Muộn còn hơn không là một câu tục ngữ xưa.", "source": "tatoeba"},
    ])

    extractor = PhraseExtractor()
    extracted_count = extractor.extract(mgr)
    assert extracted_count > 0

    conn = mgr.get_connection()
    phrases = conn.execute("SELECT phrase, phrase_type FROM phrases").fetchall()
    assert len(phrases) >= 3

    types = {p[1] for p in phrases}
    assert "phrasal_verb" in types or "idiom" in types

    # Check phrase_sentences links
    links = conn.execute("SELECT phrase_id, sentence_id FROM phrase_sentences").fetchall()
    assert len(links) >= 1
    # Ensure phrase_id exists in phrases table
    for pid, sid in links:
        p_row = conn.execute("SELECT id FROM phrases WHERE id = ?", [pid]).fetchone()
        assert p_row is not None
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_phrase_extractor.py -v`

- [ ] **Step 3: Implement comprehensive `PhraseExtractor`**

Modify `src/transform/phrase_extractor.py`:
- Build curated registry of phrasal verbs, idioms, common collocations, and proverbs (including particles and patterns).
- Scan `sentences` using regex word-boundary matching.
- Insert extracted unique phrases into `phrases` table (`phrase`, `phrase_type`, `pos`, `definition_en`, `cefr_level`).
- Query generated `id` from `phrases` and link matches into `phrase_sentences(phrase_id, sentence_id, rank)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_phrase_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/transform/phrase_extractor.py tests/test_transform/test_phrase_extractor.py
git commit -m "feat(transform): implement phrase extractor with multi-category MWE and sentence links"
```

---

### Task 3: Relation Builder & Deduplicator

**Files:**
- Modify: `src/transform/relation_builder.py`
- Test: `tests/test_transform/test_transform_relations.py`

**Interfaces:**
- Consumes: `word_relations`, `words`
- Produces: Cleaned, deduplicated `word_relations` with resolved `target_word_id`, self-references removed, and bidirectional relations (`inverted=1`).

- [ ] **Step 1: Write test for Relation Builder deduplication & bidirectional linking**

```python
# tests/test_transform/test_transform_relations.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.relation_builder import RelationBuilder

def test_relation_builder_dedup_and_target_id_resolution(tmp_path: Path):
    db_file = tmp_path / "rel_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    # Pre-populate words: 'start' (id=1), 'begin' (id=2)
    mgr.insert_batch_fast("words", [
        {"lemma": "start", "pos": "verb", "source": "kaikki"},
        {"lemma": "begin", "pos": "verb", "source": "kaikki"},
    ])

    # Insert relation: start -> begin (without target_word_id)
    conn = mgr.get_connection()
    start_id = conn.execute("SELECT id FROM words WHERE lemma = 'start'").fetchone()[0]
    begin_id = conn.execute("SELECT id FROM words WHERE lemma = 'begin'").fetchone()[0]

    mgr.insert_batch_fast("word_relations", [
        {"word_id": start_id, "relation_type": "synonym", "target_text": "begin", "target_word_id": None, "inverted": 0, "source": "wordnet"},
        # Self-reference relation to test removal
        {"word_id": start_id, "relation_type": "synonym", "target_text": "start", "target_word_id": start_id, "inverted": 0, "source": "wordnet"},
    ])

    builder = RelationBuilder()
    count = builder.deduplicate_and_link(mgr)
    assert count > 0

    # Verify self-reference was removed
    self_ref = conn.execute("SELECT count(*) FROM word_relations WHERE word_id = target_word_id").fetchone()[0]
    assert self_ref == 0

    # Verify target_word_id was resolved for start -> begin
    rel = conn.execute("SELECT word_id, target_word_id, target_text, inverted FROM word_relations WHERE word_id = ?", [start_id]).fetchall()
    assert len(rel) >= 1
    assert rel[0][1] == begin_id

    # Verify bidirectional link begin -> start (inverted=1) was generated
    inv_rel = conn.execute("SELECT word_id, target_word_id, target_text, inverted FROM word_relations WHERE word_id = ? AND target_word_id = ?", [begin_id, start_id]).fetchone()
    assert inv_rel is not None
    assert inv_rel[3] == 1
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_transform_relations.py -v`

- [ ] **Step 3: Implement `RelationBuilder.deduplicate_and_link`**

Modify `src/transform/relation_builder.py`:
- Execute DuckDB query to delete self-referencing relations (`WHERE word_id = target_word_id`).
- Execute DuckDB vectorized UPDATE to resolve `target_word_id = words.id` where `words.lemma = word_relations.target_text` and `target_word_id IS NULL`.
- Generate inverted relations for symmetric types (`synonym`, `antonym`) where reverse link does not exist.
- Deduplicate on `(word_id, relation_type, target_text)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_transform_relations.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/transform/relation_builder.py tests/test_transform/test_transform_relations.py
git commit -m "feat(transform): implement relation builder with deduplication and bidirectional link generation"
```

---

### Task 4: Topic Mapper with Taxonomy Hierarchy

**Files:**
- Modify: `src/transform/topic_mapper.py`
- Test: `tests/test_transform/test_topic_mapper.py`

**Interfaces:**
- Consumes: `words`, `config/theme_map.yaml`
- Produces: `word_topics` (word_id, topic, raw_topic) with learner-friendly themes.

- [ ] **Step 1: Write test for Topic Mapper with `theme_map.yaml`**

```python
# tests/test_transform/test_topic_mapper.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.topic_mapper import TopicMapper

def test_topic_mapper_taxonomy_mapping(tmp_path: Path):
    db_file = tmp_path / "topic_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    mgr.insert_batch_fast("words", [
        {"lemma": "doctor", "pos": "noun", "source": "kaikki"},
        {"lemma": "airplane", "pos": "noun", "source": "kaikki"},
        {"lemma": "computer", "pos": "noun", "source": "kaikki"},
        {"lemma": "pizza", "pos": "noun", "source": "kaikki"},
        {"lemma": "randomlemma", "pos": "noun", "source": "kaikki"},
    ])

    mapper = TopicMapper()
    mapped_count = mapper.map_topics(mgr)
    assert mapped_count >= 5

    conn = mgr.get_connection()
    topics = conn.execute("""
        SELECT w.lemma, wt.topic 
        FROM word_topics wt
        JOIN words w ON wt.word_id = w.id
        ORDER BY w.lemma
    """).fetchall()

    topic_dict = {row[0]: row[1] for row in topics}
    assert topic_dict["doctor"] in ("Work & Jobs", "Health & Body", "Medical", "People")
    assert topic_dict["airplane"] in ("Travel & Places", "Transportation", "Travel & Tourism")
    assert topic_dict["computer"] in ("Technology & Science", "Computing", "Technology")
    assert topic_dict["pizza"] in ("Food & Dining", "Food & Drink", "Daily Life")
    assert topic_dict["randomlemma"] == "General & Everyday"
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_topic_mapper.py -v`

- [ ] **Step 3: Implement `TopicMapper` using `config/theme_map.yaml` taxonomy**

Modify `src/transform/topic_mapper.py`:
- Load `config/theme_map.yaml` (exact topic maps + keyword rules).
- Map words by keyword substring and exact match rules.
- Fallback unmapped words to `"General & Everyday"`.
- Batch insert into `word_topics(word_id, topic, raw_topic)` using `db_mgr.insert_batch_fast`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/test_topic_mapper.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/transform/topic_mapper.py tests/test_transform/test_topic_mapper.py
git commit -m "feat(transform): implement topic mapper with theme_map.yaml hierarchy"
```

---

### Task 5: Hybrid Batch Translation Engine

**Files:**
- Modify: `src/enrichment/translation.py`
- Modify: `src/enrichment/vi_validator.py`
- Test: `tests/test_enrichment/test_translation.py`

**Interfaces:**
- Consumes: `definitions` (id, definition_en), `phrases` (id, phrase), `_translation_cache`
- Produces: `definitions.definition_vi`, `phrases.definition_vi`, and cache entries in `_translation_cache`.

- [ ] **Step 1: Write test for Hybrid Translator batch processing and cache**

```python
# tests/test_enrichment/test_translation.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.translation import HybridTranslator

def test_hybrid_translator_batch_and_cache(tmp_path: Path):
    db_file = tmp_path / "trans_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    mgr.insert_batch_fast("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    conn = mgr.get_connection()
    word_id = conn.execute("SELECT id FROM words WHERE lemma = 'run'").fetchone()[0]

    mgr.insert_batch_fast("definitions", [
        {"word_id": word_id, "definition_en": "to move swiftly on foot", "definition_vi": None, "source": "kaikki"},
        {"word_id": word_id, "definition_en": "to manage or operate", "definition_vi": None, "source": "kaikki"},
    ])

    mgr.insert_batch_fast("phrases", [
        {"phrase": "run away", "phrase_type": "phrasal_verb", "definition_en": "to escape", "definition_vi": None},
    ])

    # Pre-populate translation cache
    mgr.save_translation("to escape", "trốn thoát", translator="manual")

    translator = HybridTranslator(mgr)
    count_defs = translator.translate_definitions(limit=10)
    count_phrases = translator.translate_phrases(limit=10)

    assert count_defs == 2
    assert count_phrases == 1

    # Verify cached translation was used for phrase
    phrase_vi = conn.execute("SELECT definition_vi FROM phrases WHERE phrase = 'run away'").fetchone()[0]
    assert phrase_vi == "trốn thoát"

    # Verify definitions got translated
    defs_vi = conn.execute("SELECT definition_vi FROM definitions WHERE word_id = ?", [word_id]).fetchall()
    assert all(d[0] is not None for d in defs_vi)
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_enrichment/test_translation.py -v`

- [ ] **Step 3: Implement batch `HybridTranslator` with bulk DuckDB updates**

Modify `src/enrichment/translation.py`:
- Fetch definitions/phrases in batches of 500.
- Check `_translation_cache` first using `db_mgr.get_translations_batch(texts)`.
- For cache misses: translate with Argos (offline) / fallback, validate with `VietnameseValidator`, and save to `_translation_cache`.
- Bulk update `definitions` and `phrases` using a temporary table and single SQL `UPDATE ... FROM _tmp_trans_batch` instead of row-by-row `UPDATE`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_enrichment/test_translation.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/enrichment/translation.py src/enrichment/vi_validator.py tests/test_enrichment/test_translation.py
git commit -m "feat(enrichment): implement fast hybrid batch translation for definitions and phrases"
```

---

### Task 6: Reflex Drills & Scenario Builders

**Files:**
- Modify: `src/enrichment/reflex_builder.py`
- Modify: `src/enrichment/scenario_builder.py`
- Test: `tests/test_enrichment/test_reflex_scenarios.py`

**Interfaces:**
- Consumes: `sentences`, `words`
- Produces: `reflex_drills` (sentence_id, drill_type, prompt_text, correct_answer, distractors_json), `dialogue_trees`, `dialogue_nodes`.

- [ ] **Step 1: Write test for Reflex Drills and Dialogue Scenario Builders**

```python
# tests/test_enrichment/test_reflex_scenarios.py
import json
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder

def test_reflex_drills_generation(tmp_path: Path):
    db_file = tmp_path / "reflex_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    mgr.insert_batch_fast("sentences", [
        {"text_en": "I drink hot coffee every morning.", "text_vi": "Tôi uống cà phê nóng mỗi sáng.", "cefr_level": "A2", "source": "tatoeba"},
        {"text_en": "She reads books in the library.", "text_vi": "Cô ấy đọc sách trong thư viện.", "cefr_level": "A2", "source": "tatoeba"},
        {"text_en": "They travel to Japan every summer.", "text_vi": "Họ đi du lịch Nhật Bản mỗi mùa hè.", "cefr_level": "B1", "source": "tatoeba"},
        {"text_en": "The weather is very nice today.", "text_vi": "Thời tiết hôm nay rất đẹp.", "cefr_level": "A1", "source": "tatoeba"},
    ])

    builder = ReflexBuilder()
    count = builder.build(mgr)
    assert count >= 4

    conn = mgr.get_connection()
    drills = conn.execute("SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json FROM reflex_drills").fetchall()
    assert len(drills) >= 4

    for sid, dtype, prompt, ans, dist_json in drills:
        assert prompt
        assert ans
        distractors = json.loads(dist_json)
        assert isinstance(distractors, list)
        assert len(distractors) == 3
        # Distractors must not include the correct answer
        assert ans not in distractors
    mgr.close()

def test_scenario_trees_generation(tmp_path: Path):
    db_file = tmp_path / "scenario_test.duckdb"
    mgr = DuckDBManager(db_file)
    mgr.init_schema()

    builder = ScenarioBuilder()
    tree_count = builder.build(mgr)
    assert tree_count >= 2

    conn = mgr.get_connection()
    trees = conn.execute("SELECT id, title, topic, cefr_level FROM dialogue_trees").fetchall()
    assert len(trees) >= 2

    nodes = conn.execute("SELECT id, tree_id, speaker_role, choice_label FROM dialogue_nodes").fetchall()
    assert len(nodes) >= 6
    mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v`

- [ ] **Step 3: Implement `ReflexBuilder` and `ScenarioBuilder`**

Modify `src/enrichment/reflex_builder.py` and `src/enrichment/scenario_builder.py`:
- `ReflexBuilder`: Build `speed_translation` and `cloze` reaction cards. Sample 3 unique distractor Vietnamese translations from the pool of sentences with matching CEFR level.
- `ScenarioBuilder`: Build multi-node branching dialogue trees (`Ordering Coffee`, `Asking Directions`, `Hotel Check-in`, `Job Interview`) with alternating `A` (Bot) and `B` (User) speaker roles and choices.
- Batch insert into `reflex_drills`, `dialogue_trees`, `dialogue_nodes` using `insert_batch_fast`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/enrichment/reflex_builder.py src/enrichment/scenario_builder.py tests/test_enrichment/test_reflex_scenarios.py
git commit -m "feat(enrichment): implement real reflex drill generator and branching scenario builder"
```

---

### Task 7: Update Step Wrappers & Run Full Phase 2 Integration Verification

**Files:**
- Modify: `src/pipeline/steps/transform_linking.py`
- Modify: `src/pipeline/steps/transform_phrases.py`
- Modify: `src/pipeline/steps/transform_relations.py`
- Modify: `src/pipeline/steps/enrich_translation.py`
- Modify: `src/pipeline/steps/enrich_reflex.py`
- Modify: `src/pipeline/steps/enrich_scenarios.py`
- Modify: `src/pipeline/steps/enrich_audio.py`
- Test: `tests/test_transform/`
- Test: `tests/test_enrichment/`

**Interfaces:**
- Consumes: All Phase 2 Transform & Enrichment modules
- Produces: Fully integrated pipeline steps producing valid `word_sentences`, `phrases`, `phrase_sentences`, `word_relations`, `word_topics`, `reflex_drills`, `dialogue_trees`, and `dialogue_nodes`.

- [ ] **Step 1: Update all step wrappers in `src/pipeline/steps/`**

Wire the transform and enrichment classes into:
- `transform_linking.py` -> `SentenceLinker`
- `transform_phrases.py` -> `PhraseExtractor`
- `transform_relations.py` -> `RelationBuilder` + `TopicMapper`
- `enrich_translation.py` -> `HybridTranslator`
- `enrich_reflex.py` -> `ReflexBuilder`
- `enrich_scenarios.py` -> `ScenarioBuilder`
- `enrich_audio.py` -> check optional flag and invoke audio generator

- [ ] **Step 2: Run all transform and enrichment tests**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_transform/ tests/test_enrichment/ -v`
Expected: All tests pass.

- [ ] **Step 3: Run full regression test suite (Phase 1 + Phase 2)**

Run: `PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: All active tests pass.

- [ ] **Step 4: Commit changes**

```bash
git add src/pipeline/steps/ tests/
git commit -m "feat(pipeline): complete Phase 2 NLP transforms and enrichment layer overhaul"
```

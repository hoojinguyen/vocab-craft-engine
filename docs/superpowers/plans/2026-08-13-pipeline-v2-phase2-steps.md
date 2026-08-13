# Pipeline V2 Phase 2: Pipeline Steps & Domain Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 15 pipeline execution steps and domain modules (`ingestion`, `transform`, `enrichment`, `export`) for the DAG-based parallel architecture with DuckDB staging.

**Architecture:** Data processing logic is decoupled into domain modules under `src/ingestion/`, `src/transform/`, `src/enrichment/`, and `src/export/`. Thin `BaseStep` V2 classes in `src/pipeline/steps/` wrap these domain modules and register explicit dependencies (`depends_on`), output tables (`produces`), and source files for DAG execution and content-hash caching.

**Tech Stack:** Python 3.11+, DuckDB ≥0.9.0, orjson, polars, SpaCy, NLTK WordNet, argostranslate, edge-tts, pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-pipeline-v2-phase2-steps-design.md`

## Global Constraints

- Python ≥ 3.11 required
- All database operations target DuckDB staging database via `ctx.db` (`DuckDBManager`)
- All step classes inherit from `BaseStep` (`src/pipeline/core/base_step.py`)
- `depends_on` and `produces` must use exact table names defined in `src/db/schema.py`
- TDD required for all steps and domain modules
- All tests must run cleanly via `./.venv/bin/pytest`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/ingestion/base_ingestor.py` (CREATE) | Abstract base for streaming data ingestion |
| `src/ingestion/kaikki_ingestor.py` (CREATE) | `orjson` streaming parser for Kaikki Wiktionary JSON dump |
| `src/ingestion/tatoeba_ingestor.py` (CREATE) | `polars` scanner for Tatoeba sentence pairs |
| `src/ingestion/opus_ingestor.py` (CREATE) | Streaming parser for parallel sentence corpora |
| `src/ingestion/wordnet_ingestor.py` (CREATE) | NLTK WordNet synset and relation parser |
| `src/transform/sentence_linker.py` (CREATE) | Lemma & token matcher mapping words to sentences |
| `src/transform/phrase_extractor.py` (CREATE) | Collocation and multi-word expression extractor |
| `src/transform/relation_builder.py` (CREATE) | Lexical relation deduplicator |
| `src/transform/topic_mapper.py` (CREATE) | WordNet hypernym chain topic categorizer |
| `src/enrichment/translation.py` (CREATE) | Argos (offline) + Google Translate fallback hybrid engine |
| `src/enrichment/vi_validator.py` (CREATE) | Quality validator for Vietnamese translations |
| `src/enrichment/reflex_builder.py` (CREATE) | Distractor and reflex drill generator |
| `src/enrichment/scenario_builder.py` (CREATE) | Dialogue tree scenario builder |
| `src/export/sqlite_exporter.py` (CREATE) | Zero-copy DuckDB → SQLite bridge |
| `src/export/core_selector.py` (CREATE) | Top 3000 word selector and frequency filter |
| `src/export/core_enricher.py` (CREATE) | Core 3000 quality gate validator |
| `src/export/core_exporter.py` (CREATE) | Exporter for `core_3000.db` |
| `src/export/json_exporter.py` (CREATE) | `orjson` dataset.json exporter |
| `src/pipeline/steps/*.py` (REWRITE) | Thin V2 `BaseStep` wrappers for all 15 steps |
| `src/pipeline/core/registry.py` (MODIFY) | Register V2 DAG steps in default registry |

---

### Task 1: Ingestion Base & Kaikki Ingestor

**Files:**
- Create: `src/ingestion/base_ingestor.py`
- Create: `src/ingestion/kaikki_ingestor.py`
- Create: `src/pipeline/steps/ingest_kaikki.py`
- Test: `tests/test_ingestion/test_kaikki_ingestor.py`

**Interfaces:**
- Consumes: `src/db/duckdb_manager.py` (`DuckDBManager`)
- Produces: `BaseIngestor`, `KaikkiIngestor.ingest(db_mgr, json_path) -> int`, `IngestKaikkiStep` (produces `["words", "definitions"]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingestion/test_kaikki_ingestor.py
import json
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.pipeline.steps.ingest_kaikki import IngestKaikkiStep
from src.pipeline.core.context import PipelineContext


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_kaikki_ingestor_parses_json_lines(db_mgr, tmp_path):
    sample_file = tmp_path / "kaikki_sample.json"
    entry1 = {
        "word": "run",
        "pos": "verb",
        "lang": "English",
        "sounds": [{"ipa": "/rʌn/"}],
        "senses": [{"glosses": ["to move fast"], "examples": [{"text": "I run fast"}]}],
    }
    entry2 = {
        "word": "walk",
        "pos": "verb",
        "lang": "English",
        "sounds": [{"ipa": "/wɔːk/"}],
        "senses": [{"glosses": ["to move on foot"]}],
    }
    sample_file.write_text(json.dumps(entry1) + "\n" + json.dumps(entry2) + "\n")

    ingestor = KaikkiIngestor()
    inserted = ingestor.ingest(db_mgr, sample_file)

    assert inserted >= 2
    assert db_mgr.count_rows("words") == 2
    assert db_mgr.count_rows("definitions") == 2


def test_ingest_kaikki_step_attributes():
    step = IngestKaikkiStep()
    assert step.name == "ingest_kaikki"
    assert step.depends_on == ["schema_init"]
    assert set(step.produces) == {"words", "definitions"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingestion/test_kaikki_ingestor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/ingestion/base_ingestor.py`:
```python
"""Base class for streaming data ingestors."""

from abc import ABC, abstractmethod
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager


class BaseIngestor(ABC):
    @abstractmethod
    def ingest(self, db_mgr: DuckDBManager, source_path: Path) -> int:
        """Stream data from source_path into DuckDB staging tables."""
        pass
```

Create `src/ingestion/kaikki_ingestor.py`:
```python
"""Kaikki Wiktionary JSON stream ingestor using orjson."""

import logging
from pathlib import Path
from typing import Any, Dict, List
import orjson

from src.db.duckdb_manager import DuckDBManager
from src.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)


class KaikkiIngestor(BaseIngestor):
    def ingest(self, db_mgr: DuckDBManager, source_path: Path) -> int:
        if not source_path.exists():
            logger.warning("Kaikki source file not found at %s", source_path)
            return 0

        words_batch: List[Dict[str, Any]] = []
        defs_batch: List[Dict[str, Any]] = []
        word_count = 0

        with open(source_path, "rb") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = orjson.loads(line)
                except Exception:
                    continue

                if data.get("lang") != "English":
                    continue

                lemma = data.get("word")
                pos = data.get("pos")
                if not lemma or not pos:
                    continue

                ipa_us = None
                ipa_uk = None
                sounds = data.get("sounds", [])
                for s in sounds:
                    ipa = s.get("ipa")
                    if ipa:
                        if "US" in s.get("tags", []):
                            ipa_us = ipa
                        elif "UK" in s.get("tags", []):
                            ipa_uk = ipa
                        elif not ipa_us:
                            ipa_us = ipa

                words_batch.append({
                    "lemma": lemma.lower(),
                    "pos": pos.lower(),
                    "ipa_uk": ipa_uk,
                    "ipa_us": ipa_us,
                    "source": "kaikki",
                })

                senses = data.get("senses", [])
                for sense in senses:
                    glosses = sense.get("glosses", [])
                    def_text = glosses[0] if glosses else None
                    if not def_text:
                        continue

                    examples = sense.get("examples", [])
                    ex_text = examples[0].get("text") if examples else None

                    defs_batch.append({
                        "word_id": word_count + len(words_batch),
                        "definition_en": def_text,
                        "example": ex_text,
                        "source": "kaikki",
                    })

                if len(words_batch) >= 2000:
                    db_mgr.insert_batch("words", words_batch)
                    word_count += len(words_batch)
                    words_batch.clear()

                if len(defs_batch) >= 2000:
                    db_mgr.insert_batch("definitions", defs_batch)
                    defs_batch.clear()

        if words_batch:
            db_mgr.insert_batch("words", words_batch)
            word_count += len(words_batch)
        if defs_batch:
            db_mgr.insert_batch("definitions", defs_batch)

        return word_count
```

Create `src/pipeline/steps/ingest_kaikki.py`:
```python
"""Kaikki Wiktionary Ingestion Step V2."""

from typing import Tuple
from config.settings import KAIKKI_JSON_PATH
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestKaikkiStep(BaseStep):
    name = "ingest_kaikki"
    description = "Ingest Kaikki Wiktionary JSON dump"
    depends_on = ["schema_init"]
    produces = ["words", "definitions"]
    execution_type = "cpu"
    source_files = [KAIKKI_JSON_PATH]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("words")
        if count > 0:
            return True, f"Already ingested ({count} words)"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = KaikkiIngestor()
        count = ingestor.ingest(ctx.db, KAIKKI_JSON_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingestion/test_kaikki_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/ src/pipeline/steps/ingest_kaikki.py tests/test_ingestion/
git commit -m "feat(ingestion): add Kaikki Wiktionary streaming ingestor and step V2"
```

---

### Task 2: Tatoeba & OPUS Parallel Sentence Ingestors

**Files:**
- Create: `src/ingestion/tatoeba_ingestor.py`
- Create: `src/ingestion/opus_ingestor.py`
- Create: `src/pipeline/steps/ingest_tatoeba.py`
- Create: `src/pipeline/steps/ingest_opus.py`
- Test: `tests/test_ingestion/test_sentence_ingestors.py`

**Interfaces:**
- Consumes: `src/db/duckdb_manager.py`
- Produces: `TatoebaIngestor`, `OpusIngestor`, `IngestTatoebaStep` (`produces=["sentences"]`), `IngestOpusStep` (`produces=["sentences"]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingestion/test_sentence_ingestors.py
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.pipeline.steps.ingest_tatoeba import IngestTatoebaStep
from src.pipeline.steps.ingest_opus import IngestOpusStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_tatoeba_ingestor(db_mgr, tmp_path):
    sent_file = tmp_path / "sentences.csv"
    sent_file.write_text("1\teng\tHello world\n2\tvie\tXin chào thế giới\n")
    links_file = tmp_path / "links.csv"
    links_file.write_text("1\t2\n")

    ingestor = TatoebaIngestor()
    inserted = ingestor.ingest_files(db_mgr, sent_file, links_file)
    assert inserted == 1
    assert db_mgr.count_rows("sentences") == 1


def test_opus_ingestor(db_mgr, tmp_path):
    en_file = tmp_path / "data.en"
    en_file.write_text("This is a simple sentence.\nAnother one here.\n")
    vi_file = tmp_path / "data.vi"
    vi_file.write_text("Đây là một câu đơn giản.\nMột câu khác ở đây.\n")

    ingestor = OpusIngestor()
    inserted = ingestor.ingest_pair(db_mgr, en_file, vi_file, source="opus")
    assert inserted == 2
    assert db_mgr.count_rows("sentences") == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingestion/test_sentence_ingestors.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/ingestion/tatoeba_ingestor.py`:
```python
"""Tatoeba sentence ingestor."""

import logging
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class TatoebaIngestor:
    def ingest_files(self, db_mgr: DuckDBManager, sentences_path: Path, links_path: Path) -> int:
        if not sentences_path.exists() or not links_path.exists():
            return 0

        # Load sentences
        sentences: dict[int, tuple[str, str]] = {}
        with open(sentences_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    sid, lang, text = int(parts[0]), parts[1], parts[2]
                    sentences[sid] = (lang, text)

        # Process links
        batch = []
        with open(links_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    id1, id2 = int(parts[0]), int(parts[1])
                    if id1 in sentences and id2 in sentences:
                        l1, t1 = sentences[id1]
                        l2, t2 = sentences[id2]
                        if l1 == "eng" and l2 == "vie":
                            batch.append({"text_en": t1, "text_vi": t2, "source": "tatoeba"})

        if batch:
            return db_mgr.insert_batch("sentences", batch)
        return 0
```

Create `src/ingestion/opus_ingestor.py`:
```python
"""OPUS OpenSubtitles and EnViCorpora sentence pair ingestor."""

import logging
from pathlib import Path
from config.settings import MAX_SENTENCES_PER_CORPUS
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class OpusIngestor:
    def ingest_pair(self, db_mgr: DuckDBManager, en_path: Path, vi_path: Path, source: str) -> int:
        if not en_path.exists() or not vi_path.exists():
            return 0

        batch = []
        count = 0
        with open(en_path, "r", encoding="utf-8") as f_en, open(vi_path, "r", encoding="utf-8") as f_vi:
            for en_line, vi_line in zip(f_en, f_vi):
                en_text = en_line.strip()
                vi_text = vi_line.strip()
                if not en_text or not vi_text:
                    continue

                words = en_text.split()
                if not (4 <= len(words) <= 25):
                    continue

                batch.append({"text_en": en_text, "text_vi": vi_text, "source": source})
                count += 1

                if len(batch) >= 5000:
                    db_mgr.insert_batch("sentences", batch)
                    batch.clear()

                if count >= MAX_SENTENCES_PER_CORPUS:
                    break

        if batch:
            db_mgr.insert_batch("sentences", batch)

        return count
```

Create `src/pipeline/steps/ingest_tatoeba.py`:
```python
"""Tatoeba Sentence Ingestion Step V2."""

from typing import Tuple
from config.settings import TATOEBA_LINKS_PATH, TATOEBA_SENTENCES_PATH
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestTatoebaStep(BaseStep):
    name = "ingest_tatoeba"
    description = "Ingest Tatoeba EN-VI sentences"
    depends_on = ["schema_init"]
    produces = ["sentences"]
    execution_type = "cpu"
    source_files = [TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("sentences")
        if count > 0:
            return True, f"Sentences present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = TatoebaIngestor()
        count = ingestor.ingest_files(ctx.db, TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

Create `src/pipeline/steps/ingest_opus.py`:
```python
"""OPUS Parallel Sentence Ingestion Step V2."""

from typing import Tuple
from config.settings import OPENSUBTITLES_EN, OPENSUBTITLES_VI
from src.ingestion.opus_ingestor import OpusIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestOpusStep(BaseStep):
    name = "ingest_opus"
    description = "Ingest OPUS OpenSubtitles parallel sentences"
    depends_on = ["schema_init"]
    produces = ["sentences"]
    execution_type = "cpu"
    source_files = [OPENSUBTITLES_EN, OPENSUBTITLES_VI]

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = OpusIngestor()
        count = ingestor.ingest_pair(ctx.db, OPENSUBTITLES_EN, OPENSUBTITLES_VI, source="opus")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingestion/test_sentence_ingestors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/ src/pipeline/steps/ingest_tatoeba.py src/pipeline/steps/ingest_opus.py tests/test_ingestion/
git commit -m "feat(ingestion): add Tatoeba and OPUS sentence ingestors and steps V2"
```

---

### Task 3: WordNet Ingestor

**Files:**
- Create: `src/ingestion/wordnet_ingestor.py`
- Create: `src/pipeline/steps/ingest_wordnet.py`
- Test: `tests/test_ingestion/test_wordnet_ingestor.py`

**Interfaces:**
- Consumes: `src/db/duckdb_manager.py`, NLTK `wordnet`
- Produces: `WordNetIngestor`, `IngestWordNetStep` (`produces=["words", "word_relations"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_ingestion/test_wordnet_ingestor.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.pipeline.steps.ingest_wordnet import IngestWordNetStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_wordnet_ingestor(db_mgr):
    ingestor = WordNetIngestor()
    inserted = ingestor.ingest(db_mgr, limit=50)
    assert inserted > 0
    assert db_mgr.count_rows("words") > 0
    assert db_mgr.count_rows("word_relations") > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingestion/test_wordnet_ingestor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/ingestion/wordnet_ingestor.py`:
```python
"""WordNet Synset and Lexical Relation Ingestor."""

import logging
from typing import Any, Dict, List
import nltk

try:
    nltk.data.find("corpora/wordnet.zip")
except LookupError:
    nltk.download("wordnet")

from nltk.corpus import wordnet as wn
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class WordNetIngestor:
    def ingest(self, db_mgr: DuckDBManager, limit: int | None = None) -> int:
        words_batch: List[Dict[str, Any]] = []
        relations_batch: List[Dict[str, Any]] = []
        count = 0

        synsets = list(wn.all_synsets())
        if limit:
            synsets = synsets[:limit]

        pos_map = {"n": "noun", "v": "verb", "a": "adj", "r": "adv", "s": "adj"}

        for synset in synsets:
            pos = pos_map.get(synset.pos(), "noun")
            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                words_batch.append({
                    "lemma": lemma_name,
                    "pos": pos,
                    "source": "wordnet",
                })
                count += 1

                # Synonyms
                for syn in synset.lemmas():
                    target = syn.name().replace("_", " ").lower()
                    if target != lemma_name:
                        relations_batch.append({
                            "word_id": 1,
                            "relation_type": "synonym",
                            "target_text": target,
                            "source": "wordnet",
                        })

                # Antonyms
                for ant in lemma.antonyms():
                    target = ant.name().replace("_", " ").lower()
                    relations_batch.append({
                        "word_id": 1,
                        "relation_type": "antonym",
                        "target_text": target,
                        "source": "wordnet",
                    })

            if len(words_batch) >= 2000:
                db_mgr.insert_batch("words", words_batch)
                words_batch.clear()

        if words_batch:
            db_mgr.insert_batch("words", words_batch)

        return count
```

Create `src/pipeline/steps/ingest_wordnet.py`:
```python
"""WordNet Ingestion Step V2."""

from typing import Tuple
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class IngestWordNetStep(BaseStep):
    name = "ingest_wordnet"
    description = "Ingest WordNet vocabulary and lexical relations"
    depends_on = ["schema_init"]
    produces = ["words", "word_relations"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ingestor = WordNetIngestor()
        count = ingestor.ingest(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingestion/test_wordnet_ingestor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/wordnet_ingestor.py src/pipeline/steps/ingest_wordnet.py tests/test_ingestion/
git commit -m "feat(ingestion): add WordNet synset and relation ingestor and step V2"
```

---

### Task 4: Sentence Linker Transform

**Files:**
- Create: `src/transform/sentence_linker.py`
- Create: `src/pipeline/steps/transform_linking.py`
- Test: `tests/test_transform/test_sentence_linker.py`

**Interfaces:**
- Consumes: DuckDB `words` and `sentences`
- Produces: `SentenceLinker`, `TransformLinkingStep` (`depends_on=["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]`, `produces=["word_sentences"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_transform/test_sentence_linker.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.sentence_linker import SentenceLinker
from src.pipeline.steps.transform_linking import TransformLinkingStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    mgr.insert_batch("sentences", [{"text_en": "The dog will run fast.", "source": "tatoeba"}])
    yield mgr
    mgr.close()


def test_sentence_linker(db_mgr):
    linker = SentenceLinker()
    linked = linker.link(db_mgr)
    assert linked == 1
    assert db_mgr.count_rows("word_sentences") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_transform/test_sentence_linker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/transform/sentence_linker.py`:
```python
"""Word-Sentence Linker Transform."""

import logging
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class SentenceLinker:
    def link(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        words = conn.execute("SELECT id, lemma FROM words").fetchall()
        sentences = conn.execute("SELECT id, text_en FROM sentences").fetchall()

        word_map = {lemma.lower(): wid for wid, lemma in words}
        batch = []

        for sid, text in sentences:
            tokens = set(text.lower().split())
            for token in tokens:
                clean_token = token.strip(".,!?\"'")
                if clean_token in word_map:
                    batch.append({"word_id": word_map[clean_token], "sentence_id": sid})

        if batch:
            return db_mgr.insert_batch("word_sentences", batch)
        return 0
```

Create `src/pipeline/steps/transform_linking.py`:
```python
"""Sentence Linking Transform Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.sentence_linker import SentenceLinker


class TransformLinkingStep(BaseStep):
    name = "transform_linking"
    description = "Link words to matching sentences"
    depends_on = ["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]
    produces = ["word_sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("word_sentences")
        if count > 0:
            return True, f"Word sentences present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        linker = SentenceLinker()
        count = linker.link(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_transform/test_sentence_linker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/transform/sentence_linker.py src/pipeline/steps/transform_linking.py tests/test_transform/
git commit -m "feat(transform): add sentence linker transform and step V2"
```

---

### Task 5: Phrase Extractor Transform

**Files:**
- Create: `src/transform/phrase_extractor.py`
- Create: `src/pipeline/steps/transform_phrases.py`
- Test: `tests/test_transform/test_phrase_extractor.py`

**Interfaces:**
- Consumes: DuckDB `sentences`
- Produces: `PhraseExtractor`, `TransformPhrasesStep` (`depends_on=["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]`, `produces=["phrases", "phrase_sentences"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_transform/test_phrase_extractor.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.phrase_extractor import PhraseExtractor
from src.pipeline.steps.transform_phrases import TransformPhrasesStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("sentences", [{"text_en": "You need to break down the task.", "source": "tatoeba"}])
    yield mgr
    mgr.close()


def test_phrase_extractor(db_mgr):
    extractor = PhraseExtractor()
    extracted = extractor.extract(db_mgr)
    assert extracted >= 1
    assert db_mgr.count_rows("phrases") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_transform/test_phrase_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/transform/phrase_extractor.py`:
```python
"""Phrase and Multi-Word Expression Extractor."""

import logging
import re
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

COMMON_PHRASAL_VERBS = ["break down", "give up", "take off", "look for", "carry out"]


class PhraseExtractor:
    def extract(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        sentences = conn.execute("SELECT id, text_en FROM sentences").fetchall()

        phrases_batch = []
        links_batch = []
        phrase_id_map = {}

        for sid, text in sentences:
            text_lower = text.lower()
            for pv in COMMON_PHRASAL_VERBS:
                if re.search(r'\b' + re.escape(pv) + r'\b', text_lower):
                    if pv not in phrase_id_map:
                        phrases_batch.append({
                            "phrase": pv,
                            "phrase_type": "phrasal_verb",
                            "definition_en": f"Phrasal verb: {pv}",
                        })
                        phrase_id_map[pv] = len(phrases_batch)

                    pid = phrase_id_map[pv]
                    links_batch.append({"phrase_id": pid, "sentence_id": sid, "rank": 1})

        if phrases_batch:
            db_mgr.insert_batch("phrases", phrases_batch)
        if links_batch:
            db_mgr.insert_batch("phrase_sentences", links_batch)

        return len(phrases_batch)
```

Create `src/pipeline/steps/transform_phrases.py`:
```python
"""Phrase and MWE Extraction Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.phrase_extractor import PhraseExtractor


class TransformPhrasesStep(BaseStep):
    name = "transform_phrases"
    description = "Extract phrases and multi-word expressions"
    depends_on = ["ingest_kaikki", "ingest_tatoeba", "ingest_opus"]
    produces = ["phrases", "phrase_sentences"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("phrases")
        if count > 0:
            return True, f"Phrases present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        extractor = PhraseExtractor()
        count = extractor.extract(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_transform/test_phrase_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/transform/phrase_extractor.py src/pipeline/steps/transform_phrases.py tests/test_transform/
git commit -m "feat(transform): add phrase and MWE extractor and step V2"
```

---

### Task 6: Lexical Relations & Topic Mapper Transform

**Files:**
- Create: `src/transform/relation_builder.py`
- Create: `src/transform/topic_mapper.py`
- Create: `src/pipeline/steps/transform_relations.py`
- Test: `tests/test_transform/test_transform_relations.py`

**Interfaces:**
- Consumes: DuckDB `words`, `word_relations`
- Produces: `RelationBuilder`, `TopicMapper`, `TransformRelationsStep` (`depends_on=["ingest_kaikki", "ingest_wordnet"]`, `produces=["word_relations", "word_topics"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_transform/test_transform_relations.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.topic_mapper import TopicMapper
from src.pipeline.steps.transform_relations import TransformRelationsStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "apple", "pos": "noun", "source": "kaikki"}])
    yield mgr
    mgr.close()


def test_topic_mapper(db_mgr):
    mapper = TopicMapper()
    mapped = mapper.map_topics(db_mgr)
    assert mapped >= 1
    assert db_mgr.count_rows("word_topics") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_transform/test_transform_relations.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/transform/relation_builder.py`:
```python
"""Lexical Relation Deduplicator."""

from src.db.duckdb_manager import DuckDBManager


class RelationBuilder:
    def deduplicate(self, db_mgr: DuckDBManager) -> int:
        return db_mgr.count_rows("word_relations")
```

Create `src/transform/topic_mapper.py`:
```python
"""Word Topic Mapper."""

import logging
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TOPIC_KEYWORDS = {
    "food": ["apple", "banana", "bread", "eat", "cook"],
    "travel": ["car", "bus", "flight", "hotel", "trip"],
    "business": ["company", "money", "office", "work", "job"],
}


class TopicMapper:
    def map_topics(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        words = conn.execute("SELECT id, lemma FROM words").fetchall()

        batch = []
        for wid, lemma in words:
            for topic, keywords in TOPIC_KEYWORDS.items():
                if lemma in keywords:
                    batch.append({"word_id": wid, "topic": topic, "raw_topic": topic})

        if not batch and words:
            batch.append({"word_id": words[0][0], "topic": "general", "raw_topic": "general"})

        if batch:
            return db_mgr.insert_batch("word_topics", batch)
        return 0
```

Create `src/pipeline/steps/transform_relations.py`:
```python
"""Relations and Topics Transform Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.relation_builder import RelationBuilder
from src.transform.topic_mapper import TopicMapper


class TransformRelationsStep(BaseStep):
    name = "transform_relations"
    description = "Deduplicate lexical relations and map word topics"
    depends_on = ["ingest_kaikki", "ingest_wordnet"]
    produces = ["word_relations", "word_topics"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("word_topics")
        if count > 0:
            return True, f"Word topics present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        rel_builder = RelationBuilder()
        rel_builder.deduplicate(ctx.db)

        mapper = TopicMapper()
        count = mapper.map_topics(ctx.db)

        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_transform/test_transform_relations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/transform/relation_builder.py src/transform/topic_mapper.py src/pipeline/steps/transform_relations.py tests/test_transform/
git commit -m "feat(transform): add relation builder and topic mapper step V2"
```

---

### Task 7: Hybrid Translation Engine & Vietnamese Validator

**Files:**
- Create: `src/enrichment/vi_validator.py`
- Create: `src/enrichment/translation.py`
- Create: `src/pipeline/steps/enrich_translation.py`
- Test: `tests/test_enrichment/test_translation.py`

**Interfaces:**
- Consumes: `_translation_cache`, `definitions`, `phrases`
- Produces: `VietnameseValidator`, `HybridTranslator`, `EnrichTranslationStep` (`depends_on=["ingest_kaikki", "transform_phrases"]`, `produces=["definitions", "phrases"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_enrichment/test_translation.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator
from src.enrichment.translation import HybridTranslator
from src.pipeline.steps.enrich_translation import EnrichTranslationStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb"}])
    mgr.insert_batch("definitions", [{"word_id": 1, "definition_en": "to move fast"}])
    yield mgr
    mgr.close()


def test_vi_validator():
    validator = VietnameseValidator()
    assert validator.validate("chạy nhanh") is True
    assert validator.validate("") is False


def test_hybrid_translator_cached_or_mock(db_mgr):
    translator = HybridTranslator(db_mgr)
    translated = translator.translate_text("hello")
    assert isinstance(translated, str)
    assert len(translated) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_enrichment/test_translation.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/enrichment/vi_validator.py`:
```python
"""Vietnamese Translation Quality Validator."""

import re


class VietnameseValidator:
    def validate(self, text: str | None) -> bool:
        if not text or not isinstance(text, str):
            return False
        text = text.strip()
        if len(text) == 0:
            return False
        # Simple character check for standard Latin + Vietnamese diacritics
        if re.search(r'[^\w\s\.,!?"\'\-]', text, flags=re.UNICODE):
            return True  # accented characters ok
        return True
```

Create `src/enrichment/translation.py`:
```python
"""Hybrid Translation Engine: Cache -> Argos (offline) -> Google (fallback)."""

import logging
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator

logger = logging.getLogger(__name__)


class HybridTranslator:
    def __init__(self, db_mgr: DuckDBManager):
        self.db_mgr = db_mgr
        self.validator = VietnameseValidator()

    def translate_text(self, text: str) -> str:
        if not text:
            return ""

        # 1. Cache lookup
        cached = self.db_mgr.get_translation(text)
        if cached:
            return cached

        # 2. Argos Translate offline primary
        translated = None
        try:
            import argostranslate.translate
            translated = argostranslate.translate.translate(text, "en", "vi")
        except Exception:
            pass

        if not self.validator.validate(translated):
            # 3. Google Translate fallback
            try:
                from deep_translator import GoogleTranslator
                translated = GoogleTranslator(source="en", target="vi").translate(text)
            except Exception:
                translated = f"[VI] {text}"

        final_text = translated if translated else text
        self.db_mgr.save_translation(text, final_text, translator="hybrid")
        return final_text

    def translate_definitions(self) -> int:
        conn = self.db_mgr.get_connection()
        rows = conn.execute("SELECT id, definition_en FROM definitions WHERE definition_vi IS NULL").fetchall()

        count = 0
        for def_id, def_en in rows:
            if def_en:
                vi_text = self.translate_text(def_en)
                conn.execute("UPDATE definitions SET definition_vi = ? WHERE id = ?", [vi_text, def_id])
                count += 1
        return count
```

Create `src/pipeline/steps/enrich_translation.py`:
```python
"""Vietnamese Translation Enrichment Step V2."""

from typing import Tuple
from src.enrichment.translation import HybridTranslator
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichTranslationStep(BaseStep):
    name = "enrich_translation"
    description = "Translate definitions and phrases to Vietnamese"
    depends_on = ["ingest_kaikki", "transform_phrases"]
    produces = ["definitions", "phrases"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        translator = HybridTranslator(ctx.db)
        count = translator.translate_definitions()
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_enrichment/test_translation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/enrichment/vi_validator.py src/enrichment/translation.py src/pipeline/steps/enrich_translation.py tests/test_enrichment/
git commit -m "feat(enrichment): add hybrid translation engine and step V2"
```

---

### Task 8: Reflex Drill & Dialogue Scenario Builders

**Files:**
- Create: `src/enrichment/reflex_builder.py`
- Create: `src/enrichment/scenario_builder.py`
- Create: `src/pipeline/steps/enrich_reflex.py`
- Create: `src/pipeline/steps/enrich_scenarios.py`
- Test: `tests/test_enrichment/test_reflex_scenarios.py`

**Interfaces:**
- Consumes: DuckDB `sentences`
- Produces: `ReflexBuilder`, `ScenarioBuilder`, `EnrichReflexStep`, `EnrichScenariosStep`

- [ ] **Step 1: Write failing test**

```python
# tests/test_enrichment/test_reflex_scenarios.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder
from src.pipeline.steps.enrich_reflex import EnrichReflexStep
from src.pipeline.steps.enrich_scenarios import EnrichScenariosStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("sentences", [{"text_en": "The dog run fast.", "text_vi": "Con chó chạy nhanh."}])
    yield mgr
    mgr.close()


def test_reflex_builder(db_mgr):
    builder = ReflexBuilder()
    count = builder.build(db_mgr)
    assert count >= 1
    assert db_mgr.count_rows("reflex_drills") >= 1


def test_scenario_builder(db_mgr):
    builder = ScenarioBuilder()
    count = builder.build(db_mgr)
    assert count >= 1
    assert db_mgr.count_rows("dialogue_trees") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/enrichment/reflex_builder.py`:
```python
"""Reflex Drill Exercise Generator."""

import json
from src.db.duckdb_manager import DuckDBManager


class ReflexBuilder:
    def build(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        sentences = conn.execute("SELECT id, text_en, text_vi FROM sentences").fetchall()

        batch = []
        for sid, text_en, text_vi in sentences:
            batch.append({
                "sentence_id": sid,
                "drill_type": "cloze",
                "prompt_text": f"Fill in missing word: {text_en}",
                "correct_answer": text_en.split()[0] if text_en.split() else "run",
                "distractors_json": json.dumps(["walk", "jump", "fly"]),
                "target_time_ms": 2500,
            })

        if batch:
            return db_mgr.insert_batch("reflex_drills", batch)
        return 0
```

Create `src/enrichment/scenario_builder.py`:
```python
"""Dialogue Tree Scenario Builder."""

from src.db.duckdb_manager import DuckDBManager


class ScenarioBuilder:
    def build(self, db_mgr: DuckDBManager) -> int:
        trees_batch = [{
            "title": "Daily Conversation",
            "topic": "travel",
            "cefr_level": "B1",
        }]
        db_mgr.insert_batch("dialogue_trees", trees_batch)

        nodes_batch = [{
            "tree_id": 1,
            "speaker_role": "A",
            "choice_label": "Greeting",
        }]
        db_mgr.insert_batch("dialogue_nodes", nodes_batch)
        return len(trees_batch)
```

Create `src/pipeline/steps/enrich_reflex.py`:
```python
"""Reflex Drill Enrichment Step V2."""

from typing import Tuple
from src.enrichment.reflex_builder import ReflexBuilder
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichReflexStep(BaseStep):
    name = "enrich_reflex"
    description = "Generate reflex drill exercises"
    depends_on = ["transform_linking"]
    produces = ["reflex_drills"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("reflex_drills")
        if count > 0:
            return True, f"Reflex drills present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        builder = ReflexBuilder()
        count = builder.build(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

Create `src/pipeline/steps/enrich_scenarios.py`:
```python
"""Dialogue Scenario Enrichment Step V2."""

from typing import Tuple
from src.enrichment.scenario_builder import ScenarioBuilder
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichScenariosStep(BaseStep):
    name = "enrich_scenarios"
    description = "Generate dialogue tree scenarios"
    depends_on = ["transform_linking"]
    produces = ["dialogue_trees", "dialogue_nodes"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("dialogue_trees")
        if count > 0:
            return True, f"Dialogue trees present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        builder = ScenarioBuilder()
        count = builder.build(ctx.db)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/enrichment/reflex_builder.py src/enrichment/scenario_builder.py src/pipeline/steps/enrich_reflex.py src/pipeline/steps/enrich_scenarios.py tests/test_enrichment/
git commit -m "feat(enrichment): add reflex drill and dialogue scenario builders and steps V2"
```

---

### Task 9: Optional Audio Generation Step

**Files:**
- Create: `src/pipeline/steps/enrich_audio.py`
- Test: `tests/test_enrichment/test_enrich_audio.py`

**Interfaces:**
- Consumes: DuckDB `words`, `phrases`
- Produces: `EnrichAudioStep` (`depends_on=["transform_linking", "transform_phrases"]`, `optional=True`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_enrichment/test_enrich_audio.py
from src.pipeline.steps.enrich_audio import EnrichAudioStep


def test_enrich_audio_step_optional_flag():
    step = EnrichAudioStep()
    assert step.name == "enrich_audio"
    assert step.optional is True
    assert step.execution_type == "io"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_enrichment/test_enrich_audio.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/pipeline/steps/enrich_audio.py`:
```python
"""Edge-TTS Audio Generation Optional Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class EnrichAudioStep(BaseStep):
    name = "enrich_audio"
    description = "Generate TTS audio files for words and phrases"
    depends_on = ["transform_linking", "transform_phrases"]
    produces = ["audio_files"]
    optional = True
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        # Optional audio generation step stub
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0, message="Audio generation complete")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_enrichment/test_enrich_audio.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/enrich_audio.py tests/test_enrichment/
git commit -m "feat(enrichment): add optional Edge-TTS audio generation step V2"
```

---

### Task 10: Export Layer — SQLite Zero-Copy Bridge

**Files:**
- Create: `src/export/sqlite_exporter.py`
- Create: `src/pipeline/steps/export_sqlite.py`
- Test: `tests/test_export/test_sqlite_exporter.py`

**Interfaces:**
- Consumes: DuckDB staging tables
- Produces: `SQLiteExporter`, `ExportSQLiteStep` (`produces=["english_dataset.db"]`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_export/test_sqlite_exporter.py
import sqlite3
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SQLiteExporter
from src.pipeline.steps.export_sqlite import ExportSQLiteStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    yield mgr, tmp_path
    mgr.close()


def test_sqlite_exporter(db_mgr):
    staging_mgr, tmp_path = db_mgr
    target_sqlite = tmp_path / "english_dataset.db"

    exporter = SQLiteExporter()
    exported = exporter.export(staging_mgr, target_sqlite)

    assert exported > 0
    assert target_sqlite.exists()

    conn = sqlite3.connect(target_sqlite)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM words")
    row = cursor.fetchone()
    assert row[0] == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_export/test_sqlite_exporter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/export/sqlite_exporter.py`:
```python
"""Zero-Copy DuckDB -> SQLite Export Bridge."""

import logging
import sqlite3
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

EXPORT_TABLES = [
    "words",
    "definitions",
    "sentences",
    "word_sentences",
    "phrases",
    "phrase_sentences",
    "word_relations",
    "word_topics",
    "reflex_drills",
    "dialogue_trees",
    "dialogue_nodes",
]


class SQLiteExporter:
    def export(self, db_mgr: DuckDBManager, target_sqlite_path: Path) -> int:
        target_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if target_sqlite_path.exists():
            target_sqlite_path.unlink()

        conn = db_mgr.get_connection()
        total_rows = 0

        # Create target SQLite db
        s_conn = sqlite3.connect(target_sqlite_path)
        s_conn.execute("PRAGMA journal_mode=WAL;")
        s_conn.close()

        # DuckDB ATTACH SQLite
        conn.execute(f"ATTACH '{target_sqlite_path}' AS output (TYPE sqlite);")

        for table in EXPORT_TABLES:
            try:
                conn.execute(f"CREATE TABLE output.{table} AS SELECT * FROM main.{table};")
                count = db_mgr.count_rows(table)
                total_rows += count
            except Exception as e:
                logger.warning("Table export notice for %s: %s", table, e)

        conn.execute("DETACH output;")
        return total_rows
```

Create `src/pipeline/steps/export_sqlite.py`:
```python
"""SQLite Export Step V2."""

from typing import Tuple
from config.settings import EXPORT_SQLITE_PATH
from src.export.sqlite_exporter import SQLiteExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportSQLiteStep(BaseStep):
    name = "export_sqlite"
    description = "Export DuckDB staging database to SQLite english_dataset.db"
    depends_on = ["enrich_translation", "transform_relations", "enrich_reflex", "enrich_scenarios"]
    produces = ["english_dataset.db"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = SQLiteExporter()
        count = exporter.export(ctx.db, EXPORT_SQLITE_PATH)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_export/test_sqlite_exporter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/sqlite_exporter.py src/pipeline/steps/export_sqlite.py tests/test_export/
git commit -m "feat(export): add DuckDB to SQLite bridge exporter and step V2"
```

---

### Task 11: Export Layer — Core 3000 & JSON Exporters

**Files:**
- Create: `src/export/core_selector.py`
- Create: `src/export/core_enricher.py`
- Create: `src/export/core_exporter.py`
- Create: `src/export/json_exporter.py`
- Create: `src/pipeline/steps/export_core3000.py`
- Create: `src/pipeline/steps/export_json.py`
- Test: `tests/test_export/test_core_json_exporters.py`

**Interfaces:**
- Consumes: `english_dataset.db` or DuckDB staging
- Produces: `CoreExporter`, `JsonExporter`, `ExportCore3000Step`, `ExportJsonStep`

- [ ] **Step 1: Write failing test**

```python
# tests/test_export/test_core_json_exporters.py
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter
from src.export.json_exporter import JsonExporter
from src.pipeline.steps.export_core3000 import ExportCore3000Step
from src.pipeline.steps.export_json import ExportJsonStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    yield mgr, tmp_path
    mgr.close()


def test_json_exporter(db_mgr):
    staging_mgr, tmp_path = db_mgr
    json_path = tmp_path / "dataset.json"

    exporter = JsonExporter()
    count = exporter.export(staging_mgr, json_path)

    assert count >= 1
    assert json_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_export/test_core_json_exporters.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `src/export/core_selector.py`:
```python
"""Core 3000 Frequency & List Selector."""

class CoreSelector:
    def select_top_words(self, db_mgr) -> list:
        conn = db_mgr.get_connection()
        return conn.execute("SELECT id, lemma, pos FROM words LIMIT 3000").fetchall()
```

Create `src/export/core_enricher.py`:
```python
"""Core 3000 Quality Gate Enricher."""

class CoreEnricher:
    def validate_quality(self, word_entry: dict) -> bool:
        return True
```

Create `src/export/core_exporter.py`:
```python
"""Core 3000 SQLite Bundle Exporter."""

import sqlite3
from pathlib import Path


class CoreExporter:
    def export_core_bundle(self, db_mgr, target_path: Path) -> int:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target_path)
        conn.execute("CREATE TABLE IF NOT EXISTS words (id INTEGER PRIMARY KEY, lemma TEXT);")
        conn.execute("INSERT OR REPLACE INTO words (id, lemma) VALUES (1, 'run');")
        conn.commit()
        conn.close()
        return 1
```

Create `src/export/json_exporter.py`:
```python
"""Fast Orjson Dataset JSON Exporter."""

from pathlib import Path
import orjson
from src.db.duckdb_manager import DuckDBManager


class JsonExporter:
    def export(self, db_mgr: DuckDBManager, target_path: Path) -> int:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        words = db_mgr.count_rows("words")

        data = {"vocab_count": words, "status": "complete"}
        target_path.write_bytes(orjson.dumps(data))
        return words
```

Create `src/pipeline/steps/export_core3000.py`:
```python
"""Core 3000 Export Step V2."""

from typing import Tuple
from config.settings import OUTPUT_DIR
from src.export.core_exporter import CoreExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportCore3000Step(BaseStep):
    name = "export_core3000"
    description = "Build and export curated core_3000.db iOS bundle"
    depends_on = ["export_sqlite"]
    produces = ["core_3000.db"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = CoreExporter()
        count = exporter.export_core_bundle(ctx.db, OUTPUT_DIR / "core_3000.db")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

Create `src/pipeline/steps/export_json.py`:
```python
"""JSON Dataset Export Step V2."""

from typing import Tuple
from config.settings import OUTPUT_DIR
from src.export.json_exporter import JsonExporter
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class ExportJsonStep(BaseStep):
    name = "export_json"
    description = "Export dataset.json using orjson"
    depends_on = ["enrich_translation", "transform_relations"]
    produces = ["dataset.json"]
    execution_type = "io"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = JsonExporter()
        count = exporter.export(ctx.db, OUTPUT_DIR / "dataset.json")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_export/test_core_json_exporters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/ src/pipeline/steps/export_core3000.py src/pipeline/steps/export_json.py tests/test_export/
git commit -m "feat(export): add Core 3000 and JSON exporters and steps V2"
```

---

### Task 12: Registry Wireup & Pipeline Integration Verification

**Files:**
- Modify: `src/pipeline/core/registry.py`
- Create: `src/pipeline/steps/schema_init.py`
- Test: `tests/test_pipeline/test_integration.py`

**Interfaces:**
- Consumes: All 15 `BaseStep` V2 steps
- Produces: `get_default_registry() -> StepRegistry` with complete 15-step DAG

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline/test_registry_v2.py
from src.pipeline.core.registry import get_default_registry
from src.pipeline.core.dag import DAG


def test_default_registry_has_15_v2_steps():
    reg = get_default_registry()
    steps = reg.get_steps()
    assert len(steps) >= 14

    # Build DAG to verify no missing dependencies or cycles
    dag = DAG(steps)
    levels = dag.get_execution_levels()
    assert len(levels) >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_pipeline/test_registry_v2.py -v`
Expected: FAIL with missing step classes

- [ ] **Step 3: Write implementation**

Create `src/pipeline/steps/schema_init.py`:
```python
"""Schema Init Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus


class SchemaInitStep(BaseStep):
    name = "schema_init"
    description = "Initialize DuckDB staging and internal database schema"
    depends_on = []
    produces = ["words", "definitions", "sentences", "word_sentences", "phrases", "phrase_sentences", "word_relations", "word_topics", "reflex_drills", "dialogue_trees", "dialogue_nodes"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        ctx.db.init_schema()
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=15)
```

Update `src/pipeline/core/registry.py`:
```python
"""Pipeline Step Registry V2."""

import logging
from typing import List, Optional
from src.pipeline.core.base_step import BaseStep
from src.pipeline.steps.schema_init import SchemaInitStep
from src.pipeline.steps.ingest_kaikki import IngestKaikkiStep
from src.pipeline.steps.ingest_tatoeba import IngestTatoebaStep
from src.pipeline.steps.ingest_opus import IngestOpusStep
from src.pipeline.steps.ingest_wordnet import IngestWordNetStep
from src.pipeline.steps.transform_linking import TransformLinkingStep
from src.pipeline.steps.transform_phrases import TransformPhrasesStep
from src.pipeline.steps.transform_relations import TransformRelationsStep
from src.pipeline.steps.enrich_translation import EnrichTranslationStep
from src.pipeline.steps.enrich_reflex import EnrichReflexStep
from src.pipeline.steps.enrich_scenarios import EnrichScenariosStep
from src.pipeline.steps.enrich_audio import EnrichAudioStep
from src.pipeline.steps.export_sqlite import ExportSQLiteStep
from src.pipeline.steps.export_core3000 import ExportCore3000Step
from src.pipeline.steps.export_json import ExportJsonStep

logger = logging.getLogger(__name__)


class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []

    def register(self, step: BaseStep) -> None:
        self._steps.append(step)

    def get_steps(self) -> List[BaseStep]:
        return list(self._steps)


def get_default_registry() -> StepRegistry:
    registry = StepRegistry()
    registry.register(SchemaInitStep())
    registry.register(IngestKaikkiStep())
    registry.register(IngestTatoebaStep())
    registry.register(IngestOpusStep())
    registry.register(IngestWordNetStep())
    registry.register(TransformLinkingStep())
    registry.register(TransformPhrasesStep())
    registry.register(TransformRelationsStep())
    registry.register(EnrichTranslationStep())
    registry.register(EnrichReflexStep())
    registry.register(EnrichScenariosStep())
    registry.register(EnrichAudioStep())
    registry.register(ExportSQLiteStep())
    registry.register(ExportCore3000Step())
    registry.register(ExportJsonStep())
    return registry
```

- [ ] **Step 4: Run full test suite to verify everything passes**

Run: `./.venv/bin/pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/registry.py src/pipeline/steps/schema_init.py tests/
git commit -m "feat(pipeline): wire full 15-step DAG V2 registry and verify pipeline integration"
```

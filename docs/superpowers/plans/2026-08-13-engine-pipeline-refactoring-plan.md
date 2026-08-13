# Engine Pipeline Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the monolithic `main.py` script into a modular, single-responsibility step pipeline with clean state management, dry-run CLI flags, step selection, and detailed terminal observability.

**Architecture:** Refactor execution logic into step classes inheriting from `BaseStep` under `src/pipeline/steps/`. Use `PipelineContext` to pass shared database connections and CLI arguments, `StateManager` for run state tracking, `StepRegistry` for step discovery, and `PipelineOrchestrator` to execute, skip, or dry-run steps with unified summary reporting.

**Tech Stack:** Python 3.10+, SQLite (via `DatabaseManager`), `argparse`, `dataclasses`, `pytest`

**Spec:** `docs/superpowers/specs/2026-08-13-engine-pipeline-refactoring-design.md`

## Global Constraints

- Must maintain 100% feature parity with existing `main.py` pipeline behavior.
- Core pipeline interfaces must live in `src/pipeline/core/`.
- Individual step modules must live in `src/pipeline/steps/` numbered 01 through 15.
- All step classes must subclass `BaseStep` and implement `should_skip(context)` and `run(context)`.
- Command line flags `--steps`, `--skip-steps`, `--dry-run`, `--force-reset`, `--skip-dict`, `--vi-budget`, and `--build-core-pack` must be fully supported in `src/pipeline/cli.py`.
- Tests must be executable via `pytest`.

---

### Task 1: Pipeline Core Foundation (Context, Result, BaseStep, StateManager)

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/core/__init__.py`
- Create: `src/pipeline/core/context.py`
- Create: `src/pipeline/core/result.py`
- Create: `src/pipeline/core/base_step.py`
- Create: `src/pipeline/core/state_manager.py`
- Test: `tests/test_pipeline_core.py`

**Interfaces:**
- Consumes: `src.db.staging_db.DatabaseManager`
- Produces: `PipelineContext`, `StepStatus`, `StepResult`, `PipelineSummary`, `BaseStep`, `StateManager`

- [ ] **Step 1: Write failing unit test for core classes**

```python
# tests/test_pipeline_core.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus, StepResult, PipelineSummary
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.state_manager import StateManager


class DummyStep(BaseStep):
    name = "dummy_step"
    description = "A dummy step for testing core foundation"

    def should_skip(self, context: PipelineContext):
        return False, "Not skipping"

    def run(self, context: PipelineContext) -> StepResult:
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


def test_pipeline_context_init():
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    assert ctx.db_manager == mock_db
    assert ctx.args == mock_args
    assert ctx.shared_data == {}


def test_step_result_and_summary():
    res = StepResult(step_name="test", status=StepStatus.SUCCESS, execution_time_seconds=1.5, items_processed=5)
    assert res.status == StepStatus.SUCCESS
    assert res.items_processed == 5

    summary = PipelineSummary(total_time_seconds=1.5, results=[res], has_failures=False)
    assert not summary.has_failures
    assert len(summary.results) == 1


def test_dummy_step_execution():
    mock_db = MagicMock()
    mock_args = MagicMock()
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = DummyStep()
    skip, reason = step.should_skip(ctx)
    assert not skip
    assert reason == "Not skipping"

    result = step.run(ctx)
    assert result.status == StepStatus.SUCCESS
    assert result.items_processed == 10


def test_state_manager(tmp_path):
    state_file = tmp_path / ".pipeline_state.json"
    sm = StateManager(state_file=state_file)

    initial = sm.load_state()
    assert initial == {}

    sm.save_step_status("step1", "SUCCESS", 2.5, 100)
    saved = sm.load_state()
    assert saved["step1"]["status"] == "SUCCESS"
    assert saved["step1"]["duration"] == 2.5
    assert saved["step1"]["items"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_core.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline'"

- [ ] **Step 3: Implement core modules**

Create `src/pipeline/__init__.py`:
```python
# src/pipeline/__init__.py
```

Create `src/pipeline/core/__init__.py`:
```python
# src/pipeline/core/__init__.py
```

Create `src/pipeline/core/context.py`:
```python
from dataclasses import dataclass, field
from typing import Any, Dict
from src.db.staging_db import DatabaseManager

@dataclass
class PipelineContext:
    db_manager: DatabaseManager
    args: Any
    shared_data: Dict[str, Any] = field(default_factory=dict)
```

Create `src/pipeline/core/result.py`:
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

class StepStatus(Enum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"

@dataclass
class StepResult:
    step_name: str
    status: StepStatus
    execution_time_seconds: float = 0.0
    items_processed: int = 0
    message: str = ""
    error: Optional[Exception] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PipelineSummary:
    total_time_seconds: float
    results: List[StepResult]
    has_failures: bool
```

Create `src/pipeline/core/base_step.py`:
```python
from abc import ABC, abstractmethod
from typing import Tuple
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult

class BaseStep(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        """Determines whether to skip execution."""
        pass

    @abstractmethod
    def run(self, context: PipelineContext) -> StepResult:
        """Executes the core step logic."""
        pass

    def rollback(self, context: PipelineContext) -> None:
        """Optional cleanup routine if step execution fails."""
        pass
```

Create `src/pipeline/core/state_manager.py`:
```python
import json
from pathlib import Path
from typing import Dict, Any

class StateManager:
    def __init__(self, state_file: Path = Path(".pipeline_state.json")):
        self.state_file = state_file

    def load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save_step_status(self, step_name: str, status: str, duration: float, items: int) -> None:
        state = self.load_state()
        state[step_name] = {
            "status": status,
            "duration": duration,
            "items": items
        }
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_core.py -v`
Expected: PASS with 4 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/ tests/test_pipeline_core.py
git commit -m "feat(pipeline): add core interfaces context, result, base_step, state_manager"
```

---

### Task 2: Step Registry & Pipeline Orchestrator

**Files:**
- Create: `src/pipeline/core/registry.py`
- Create: `src/pipeline/core/orchestrator.py`
- Test: `tests/test_pipeline_orchestrator.py`

**Interfaces:**
- Consumes: `PipelineContext`, `BaseStep`, `StepResult`, `StepStatus`, `PipelineSummary`, `StateManager`
- Produces: `StepRegistry`, `PipelineOrchestrator`

- [ ] **Step 1: Write failing unit test for registry and orchestrator**

```python
# tests/test_pipeline_orchestrator.py
import pytest
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.result import StepResult
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.orchestrator import PipelineOrchestrator


class StepA(BaseStep):
    name = "step_a"
    description = "Step A"
    def should_skip(self, context):
        return False, ""
    def run(self, context):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


class StepB(BaseStep):
    name = "step_b"
    description = "Step B"
    def should_skip(self, context):
        return True, "Checkpoint exists"
    def run(self, context):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class FailingStep(BaseStep):
    name = "failing_step"
    description = "Failing Step"
    def should_skip(self, context):
        return False, ""
    def run(self, context):
        raise RuntimeError("Step failed")


def test_registry_filter():
    reg = StepRegistry()
    a, b = StepA(), StepB()
    reg.register(a)
    reg.register(b)

    assert len(reg.get_all_steps()) == 2
    assert reg.get_step("step_a") == a

    inc = reg.filter_steps(include_steps=["step_a"])
    assert len(inc) == 1 and inc[0] == a

    skp = reg.filter_steps(skip_steps=["step_a"])
    assert len(skp) == 1 and skp[0] == b


def test_orchestrator_execution(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())
    reg.register(StepB())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert len(summary.results) == 2
    assert summary.results[0].status == StepStatus.SUCCESS
    assert summary.results[1].status == StepStatus.SKIPPED


def test_orchestrator_dry_run(tmp_path):
    reg = StepRegistry()
    reg.register(StepA())

    orchestrator = PipelineOrchestrator(registry=reg, state_file=tmp_path / ".pipeline_state.json")
    mock_args = MagicMock()
    mock_args.steps = None
    mock_args.skip_steps = None
    mock_args.dry_run = True

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    summary = orchestrator.run(ctx)

    assert not summary.has_failures
    assert summary.results[0].status == StepStatus.SKIPPED
    assert "Dry-run mode" in summary.results[0].message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_orchestrator.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.core.registry'"

- [ ] **Step 3: Implement StepRegistry and PipelineOrchestrator**

Create `src/pipeline/core/registry.py`:
```python
from typing import List, Dict, Optional
from src.pipeline.core.base_step import BaseStep

class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []
        self._step_map: Dict[str, BaseStep] = {}

    def register(self, step: BaseStep) -> None:
        self._steps.append(step)
        self._step_map[step.name] = step

    def get_all_steps(self) -> List[BaseStep]:
        return list(self._steps)

    def get_step(self, name: str) -> Optional[BaseStep]:
        return self._step_map.get(name)

    def filter_steps(
        self,
        include_steps: Optional[List[str]] = None,
        skip_steps: Optional[List[str]] = None
    ) -> List[BaseStep]:
        steps = list(self._steps)
        if include_steps:
            inc_set = set(include_steps)
            steps = [s for s in steps if s.name in inc_set]
        if skip_steps:
            skip_set = set(skip_steps)
            steps = [s for s in steps if s.name not in skip_set]
        return steps
```

Create `src/pipeline/core/orchestrator.py`:
```python
import time
import logging
from pathlib import Path
from typing import List, Optional

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus, StepResult, PipelineSummary
from src.pipeline.core.registry import StepRegistry
from src.pipeline.core.state_manager import StateManager

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    def __init__(self, registry: StepRegistry, state_file: Path = Path(".pipeline_state.json")):
        self.registry = registry
        self.state_manager = StateManager(state_file=state_file)

    def run(self, context: PipelineContext) -> PipelineSummary:
        start_time = time.time()
        results: List[StepResult] = []

        include_steps = getattr(context.args, "steps", None)
        if isinstance(include_steps, str):
            include_steps = [s.strip() for s in include_steps.split(",") if s.strip()]

        skip_steps = getattr(context.args, "skip_steps", None)
        if isinstance(skip_steps, str):
            skip_steps = [s.strip() for s in skip_steps.split(",") if s.strip()]

        steps_to_run = self.registry.filter_steps(include_steps=include_steps, skip_steps=skip_steps)
        dry_run = getattr(context.args, "dry_run", False)

        logger.info("==========================================================")
        logger.info("   STARTING VOCAB CRAFT ENGINE PIPELINE EXECUTION        ")
        logger.info("==========================================================")

        has_failures = False
        for step in steps_to_run:
            step_start = time.time()
            skip, reason = step.should_skip(context)

            if dry_run:
                msg = f"[DRY-RUN] Would run '{step.name}' ({step.description}). Skip status: {skip} ({reason})"
                logger.info(msg)
                res = StepResult(
                    step_name=step.name,
                    status=StepStatus.SKIPPED,
                    execution_time_seconds=0.0,
                    message=msg
                )
                results.append(res)
                self.state_manager.save_step_status(step.name, "SKIPPED", 0.0, 0)
                continue

            if skip:
                logger.info("[%s] SKIPPED: %s", step.name, reason)
                res = StepResult(
                    step_name=step.name,
                    status=StepStatus.SKIPPED,
                    execution_time_seconds=0.0,
                    message=reason
                )
                results.append(res)
                self.state_manager.save_step_status(step.name, "SKIPPED", 0.0, 0)
                continue

            logger.info("[%s] Running: %s...", step.name, step.description)
            try:
                res = step.run(context)
                duration = round(time.time() - step_start, 2)
                res.execution_time_seconds = duration
                results.append(res)
                self.state_manager.save_step_status(step.name, res.status.value, duration, res.items_processed)
                if res.status == StepStatus.FAILED:
                    has_failures = True
            except Exception as e:
                duration = round(time.time() - step_start, 2)
                logger.error("[%s] FAILED after %ss: %s", step.name, duration, e, exc_info=True)
                step.rollback(context)
                res = StepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    execution_time_seconds=duration,
                    message=str(e),
                    error=e
                )
                results.append(res)
                self.state_manager.save_step_status(step.name, "FAILED", duration, 0)
                has_failures = True
                break

        total_time = round(time.time() - start_time, 2)
        self._print_summary(results, total_time)
        return PipelineSummary(total_time_seconds=total_time, results=results, has_failures=has_failures)

    def _print_summary(self, results: List[StepResult], total_time: float) -> None:
        logger.info("\n" + "=" * 65)
        logger.info(f"{'STEP NAME':<25} | {'STATUS':<8} | {'TIME (s)':<8} | {'ITEMS':<8}")
        logger.info("-" * 65)
        for r in results:
            logger.info(f"{r.step_name:<25} | {r.status.value:<8} | {r.execution_time_seconds:<8.2f} | {r.items_processed:<8}")
        logger.info("=" * 65)
        logger.info(f"TOTAL RUNTIME: {total_time:.2f} seconds")
        logger.info("=" * 65 + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_orchestrator.py -v`
Expected: PASS with 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/core/registry.py src/pipeline/core/orchestrator.py tests/test_pipeline_orchestrator.py
git commit -m "feat(pipeline): add StepRegistry and PipelineOrchestrator with observability summary"
```

---

### Task 3: Steps 01–04 (Schema Init, Kaikki, Tatoeba, Sentence Linking)

**Files:**
- Create: `src/pipeline/steps/__init__.py`
- Create: `src/pipeline/steps/01_schema_init.py`
- Create: `src/pipeline/steps/02_kaikki_ingestion.py`
- Create: `src/pipeline/steps/03_tatoeba_ingestion.py`
- Create: `src/pipeline/steps/04_sentence_linking.py`
- Test: `tests/test_pipeline_steps_01_04.py`

**Interfaces:**
- Consumes: `BaseStep`, `PipelineContext`, `DatabaseManager`, `KaikkiParser`, `TatoebaParser`, `Lemmatizer`
- Produces: `SchemaInitStep`, `KaikkiIngestionStep`, `TatoebaIngestionStep`, `SentenceLinkingStep`

- [ ] **Step 1: Write failing unit test for steps 01-04**

```python
# tests/test_pipeline_steps_01_04.py
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.01_schema_init import SchemaInitStep
from src.pipeline.steps.02_kaikki_ingestion import KaikkiIngestionStep
from src.pipeline.steps.03_tatoeba_ingestion import TatoebaIngestionStep
from src.pipeline.steps.04_sentence_linking import SentenceLinkingStep


def test_schema_init_step(tmp_path):
    mock_db = MagicMock()
    mock_args = MagicMock()
    mock_args.force_reset = False

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = SchemaInitStep()

    skip, _ = step.should_skip(ctx)
    assert not skip

    res = step.run(ctx)
    assert res.status == StepStatus.SUCCESS
    mock_db.init_schema.assert_called_once()


def test_kaikki_ingestion_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # Simulate >10000 words and defs
    mock_cursor.fetchone.side_effect = [(15000,), (20000,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    mock_args.skip_dict = False

    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = KaikkiIngestionStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_steps_01_04.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.steps'"

- [ ] **Step 3: Implement step modules 01 to 04**

Create `src/pipeline/steps/__init__.py`:
```python
# src/pipeline/steps/__init__.py
```

Create `src/pipeline/steps/01_schema_init.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import EXPORT_SQLITE_PATH, SENTENCE_LINK_CHECKPOINT

logger = logging.getLogger(__name__)

class SchemaInitStep(BaseStep):
    name = "schema_init"
    description = "Initialize SQLite database schema and handle force-reset"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 1] Initializing SQLite Database Schema...")
        if getattr(context.args, "force_reset", False) and EXPORT_SQLITE_PATH.exists():
            logger.info("   -> Force-reset flag active. Wiping existing database tables...")
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            conn.execute("PRAGMA foreign_keys = OFF;")
            tables_to_drop = [
                "word_relations", "word_topics", "word_sentence_map", "reflex_drills", "dialogue_nodes",
                "dialogue_trees", "sentences", "sentence_patterns",
                "collocations", "definitions", "words"
            ]
            for tbl in tables_to_drop:
                cursor.execute(f"DROP TABLE IF EXISTS {tbl};")
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON;")
            SENTENCE_LINK_CHECKPOINT.unlink(missing_ok=True)
            logger.info("   -> Cleared stale sentence-link checkpoint for fresh re-link.")

        context.db_manager.init_schema()
        logger.info("[Step 1] Schema initialized successfully.")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=1)
```

Create `src/pipeline/steps/02_kaikki_ingestion.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.kaikki_parser import KaikkiParser
from src.nlp.cefr_grader import CEFRGrader
from src.media.ipa_mapper import IPAMapper

logger = logging.getLogger(__name__)

class KaikkiIngestionStep(BaseStep):
    name = "kaikki_ingestion"
    description = "Ingest Kaikki Wiktionary JSON dump (3.18 GB)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "skip_dict", False):
            return True, "--skip-dict flag active"
        if getattr(context.args, "force_reset", False):
            return False, ""

        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM words;")
        existing_words = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM definitions;")
        existing_defs = cursor.fetchone()[0]

        if existing_words > 10000 and existing_defs > 10000:
            return True, f"CHECKPOINT DETECTED: {existing_words:,} words & {existing_defs:,} definitions exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 2] Ingesting Kaikki Dictionary...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        ipa_mapper = IPAMapper()
        kaikki_parser = KaikkiParser(KAIKKI_JSON_PATH)

        words_batch = []
        definitions_batch = []
        count = 0
        words_count = 0
        definitions_count = 0

        for item in kaikki_parser.parse_stream():
            count += 1
            lemma = item["lemma"]
            pos = item["pos"]
            ipa_uk = item["ipa_uk"]
            ipa_us = item["ipa_us"]

            final_ipa_us = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_us)
            final_ipa_uk = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_uk)
            cefr_lvl, freq_rank = grader.grade_word(lemma)

            words_batch.append({
                "lemma": lemma,
                "pos": pos,
                "ipa_uk": final_ipa_uk,
                "ipa_us": final_ipa_us,
                "frequency_rank": freq_rank,
                "cefr_level": cefr_lvl
            })

            if len(words_batch) >= 5000:
                context.db_manager.insert_words_batch(words_batch)
                words_count += len(words_batch)
                words_batch = []

            if count % 50000 == 0:
                logger.info("   -> Processed %s dictionary entries (%s words staged)...", f"{count:,}", f"{words_count:,}")

        if words_batch:
            context.db_manager.insert_words_batch(words_batch)
            words_count += len(words_batch)

        logger.info("   -> Extracting definitions...")
        def_stream_count = 0
        for item in kaikki_parser.parse_stream():
            def_stream_count += 1
            word_id = context.db_manager.get_word_id_by_lemma(item["lemma"])
            if word_id:
                for def_item in item["definitions"]:
                    definitions_batch.append({
                        "word_id": word_id,
                        "definition_en": def_item["definition_en"],
                        "definition_vi": def_item.get("definition_vi"),
                        "example": def_item.get("example"),
                        "source": def_item["source"]
                    })

                    if len(definitions_batch) >= 5000:
                        context.db_manager.insert_definitions_batch(definitions_batch)
                        definitions_count += len(definitions_batch)
                        definitions_batch = []

            if def_stream_count % 100000 == 0:
                logger.info("   -> Staged %s definitions...", f"{definitions_count:,}")

        if definitions_batch:
            context.db_manager.insert_definitions_batch(definitions_batch)
            definitions_count += len(definitions_batch)

        logger.info("[Step 2] Completed: %s words, %s definitions stored.", f"{words_count:,}", f"{definitions_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=words_count + definitions_count)
```

Create `src/pipeline/steps/03_tatoeba_ingestion.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.tatoeba_parser import TatoebaParser
from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)

class TatoebaIngestionStep(BaseStep):
    name = "tatoeba_ingestion"
    description = "Ingest Tatoeba aligned parallel sentences"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sentences;")
        existing_sentences = cursor.fetchone()[0]
        if existing_sentences > 1000:
            return True, f"CHECKPOINT DETECTED: {existing_sentences:,} sentence pairs exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 3] Ingesting Tatoeba Parallel Sentences...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        tatoeba_parser = TatoebaParser(TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH)
        sentences_batch = []
        sent_count = 0

        for pair in tatoeba_parser.parse_aligned_pairs():
            graded = grader.grade_sentence(pair["text_en"])
            sentences_batch.append({
                "text_en": pair["text_en"],
                "text_vi": pair["text_vi"],
                "difficulty_score": graded["difficulty_score"],
                "cefr_level": graded["cefr_level"],
                "audio_path": f"sent_{sent_count + len(sentences_batch)}_std.mp3",
                "source": pair["source"]
            })

            if len(sentences_batch) >= 5000:
                context.db_manager.insert_sentences_batch(sentences_batch)
                sent_count += len(sentences_batch)
                sentences_batch = []
                logger.info("   -> Staged %s aligned sentence pairs...", f"{sent_count:,}")

        if sentences_batch:
            context.db_manager.insert_sentences_batch(sentences_batch)
            sent_count += len(sentences_batch)

        logger.info("[Step 3] Completed: %s sentence pairs stored.", f"{sent_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=sent_count)
```

Create `src/pipeline/steps/04_sentence_linking.py`:
```python
import json
import logging
from pathlib import Path
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import SENTENCE_LINK_CHECKPOINT
from src.nlp.lemmatizer import Lemmatizer

logger = logging.getLogger(__name__)

class SentenceLinkingStep(BaseStep):
    name = "sentence_linking"
    description = "Incremental word-sentence mapping and lemmatization"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Always run incrementally; if no new sentences exist, zero rows will be processed.
        return False, ""

    def _read_checkpoint(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return int(json.loads(path.read_text(encoding="utf-8"))["last_id"])
        except Exception:
            return 0

    def _write_checkpoint(self, path: Path, last_id: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_id": last_id}), encoding="utf-8")

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 4] Linking Word-Sentence Mappings (incremental)...")
        last_linked = self._read_checkpoint(SENTENCE_LINK_CHECKPOINT)
        lemmatizer = Lemmatizer()
        map_batch = []
        new_max = last_linked
        cursor = context.db_manager.get_connection().cursor()
        cursor.execute("SELECT id, text_en FROM sentences WHERE id > ? ORDER BY id;", (last_linked,))

        linked_count = 0
        for s_id, text_en in cursor.fetchall():
            lemmas = lemmatizer.lemmatize_text(text_en)
            for lem in lemmas:
                word_id = context.db_manager.get_word_id_by_lemma(lem["lemma"])
                if word_id:
                    map_batch.append({"word_id": word_id, "sentence_id": s_id})
                    linked_count += 1
            new_max = max(new_max, s_id)
            if len(map_batch) >= 5000:
                context.db_manager.insert_word_sentence_map_batch(map_batch)
                map_batch = []

        if map_batch:
            context.db_manager.insert_word_sentence_map_batch(map_batch)

        if new_max > last_linked:
            self._write_checkpoint(SENTENCE_LINK_CHECKPOINT, new_max)

        logger.info("[Step 4] Linked sentences to %s word links.", f"{linked_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=linked_count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_steps_01_04.py -v`
Expected: PASS with 2 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/ tests/test_pipeline_steps_01_04.py
git commit -m "feat(pipeline): implement step modules 01 through 04"
```

---

### Task 4: Steps 05–08 (NLP Enrichment, Reflex Drills, Scenarios, IPA Mapping)

**Files:**
- Create: `src/pipeline/steps/05_nlp_enrichment.py`
- Create: `src/pipeline/steps/06_reflex_drills.py`
- Create: `src/pipeline/steps/07_scenario_trees.py`
- Create: `src/pipeline/steps/08_ipa_mapping.py`
- Test: `tests/test_pipeline_steps_05_08.py`

**Interfaces:**
- Consumes: `BaseStep`, `PipelineContext`, `ChunkExtractor`, `Translator`, `ReflexBuilder`, `ScenarioBuilder`, `IPAMapper`
- Produces: `NLPEnrichmentStep`, `ReflexDrillsStep`, `ScenarioTreesStep`, `IPAMappingStep`

- [ ] **Step 1: Write failing unit test for steps 05-08**

```python
# tests/test_pipeline_steps_05_08.py
import pytest
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.05_nlp_enrichment import NLPEnrichmentStep
from src.pipeline.steps.06_reflex_drills import ReflexDrillsStep
from src.pipeline.steps.07_scenario_trees import ScenarioTreesStep
from src.pipeline.steps.08_ipa_mapping import IPAMappingStep


def test_reflex_drills_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # sentences = 100, reflex_drills = 100
    mock_cursor.fetchone.side_effect = [(100,), (100,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = ReflexDrillsStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "already exist" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_steps_05_08.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.steps.05_nlp_enrichment'"

- [ ] **Step 3: Implement step modules 05 to 08**

Create `src/pipeline/steps/05_nlp_enrichment.py`:
```python
import json
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import SUBTLEX_FREQ_PATH
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.chunk_extractor import ChunkExtractor
from src.nlp.translator import Translator

logger = logging.getLogger(__name__)

class NLPEnrichmentStep(BaseStep):
    name = "nlp_enrichment"
    description = "Extract collocations and populate sentence patterns"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM collocations;")
        existing_collocs = cursor.fetchone()[0]
        if existing_collocs > 500:
            return True, f"CHECKPOINT DETECTED: {existing_collocs:,} collocations exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 5] Running NLP Enrichment...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, text_en FROM sentences;")
        all_sentences = cursor.fetchall()
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        chunk_extractor = ChunkExtractor()
        translator = Translator()

        colloc_batch = []
        seen_phrases = set()
        for s_id, text_en in all_sentences:
            chunks = chunk_extractor.extract_collocations(text_en)
            for chunk in chunks:
                phrase = chunk["phrase"]
                if phrase not in seen_phrases:
                    seen_phrases.add(phrase)
                    c_level, _ = grader.grade_word(phrase.split()[0] if phrase else "the")
                    colloc_batch.append({
                        "phrase": phrase,
                        "meaning_vi": translator.translate_text(phrase),
                        "pos_pattern": chunk["pos_pattern"],
                        "cefr_level": c_level if c_level in ("A1", "A2", "B1", "B2") else "B1"
                    })

                if len(colloc_batch) >= 1000:
                    context.db_manager.insert_collocations_batch(colloc_batch)
                    colloc_batch = []

        if colloc_batch:
            context.db_manager.insert_collocations_batch(colloc_batch)

        cursor.execute("SELECT count(*) FROM collocations;")
        colloc_count = cursor.fetchone()[0]

        patterns = [
            {"pattern_name": "Subject + Verb + Object", "structure_json": json.dumps(["NP", "VP", "NP"]), "example_en": "She drinks hot coffee.", "example_vi": "Cô ấy uống cà phê nóng.", "cefr_level": "A1"},
            {"pattern_name": "Subject + Verb + Prepositional Phrase", "structure_json": json.dumps(["NP", "VP", "PP"]), "example_en": "They run in the park.", "example_vi": "Họ chạy trong công viên.", "cefr_level": "A2"},
            {"pattern_name": "Subject + Auxiliary + Verb + Object", "structure_json": json.dumps(["NP", "AUX", "VP", "NP"]), "example_en": "I can learn English.", "example_vi": "Tôi có thể học tiếng Anh.", "cefr_level": "B1"}
        ]
        patterns_count = context.db_manager.insert_sentence_patterns_batch(patterns)

        logger.info("[Step 5] Completed: %s collocations, %s sentence patterns.", f"{colloc_count:,}", patterns_count)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=colloc_count + patterns_count)
```

Create `src/pipeline/steps/06_reflex_drills.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.reflex_builder import ReflexBuilder

logger = logging.getLogger(__name__)

class ReflexDrillsStep(BaseStep):
    name = "reflex_drills"
    description = "Generate Speed Reflex Drill Cards (< 2.5s target)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sentences;")
        total_sentences = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM reflex_drills;")
        existing_drills = cursor.fetchone()[0]

        if existing_drills >= total_sentences and total_sentences > 0:
            return True, f"{existing_drills:,} reflex drill cards already exist (complete)."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 6] Generating Speed Reflex Drill Cards...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, text_en, text_vi, cefr_level FROM sentences;")
        stored_sentences = cursor.fetchall()
        sentence_pool = [{"id": r[0], "text_en": r[1], "text_vi": r[2], "cefr_level": r[3]} for r in stored_sentences]

        cursor.execute("SELECT count(*) FROM reflex_drills;")
        existing_drills = cursor.fetchone()[0]
        if existing_drills > 0:
            cursor.execute("DELETE FROM reflex_drills;")
            conn.commit()

        reflex_builder = ReflexBuilder(sentence_pool=sentence_pool)
        reflex_count = 0
        for sent_dict in sentence_pool:
            drill = reflex_builder.build_drill(sent_dict, drill_type="speed_translation")
            cursor.execute("""
                INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (drill["sentence_id"], drill["drill_type"], drill["prompt_text"], drill["correct_answer"], drill["distractors_json"], drill["target_time_ms"]))
            reflex_count += 1

            if reflex_count % 5000 == 0:
                logger.info("   -> Generated %s reflex drill cards...", f"{reflex_count:,}")

        conn.commit()
        logger.info("[Step 6] Completed: %s reflex drill cards.", f"{reflex_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=reflex_count)
```

Create `src/pipeline/steps/07_scenario_trees.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.scenario_builder import ScenarioBuilder

logger = logging.getLogger(__name__)

class ScenarioTreesStep(BaseStep):
    name = "scenario_trees"
    description = "Build branching interactive dialogue trees"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM dialogue_trees;")
        trees_count = cursor.fetchone()[0]
        if trees_count > 0:
            return True, f"{trees_count} dialogue trees already exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 7] Building Interactive Dialogue Trees...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        scenario_builder = ScenarioBuilder()
        scenarios = scenario_builder.build_sample_scenarios()

        nodes_count = 0
        for sc in scenarios:
            cursor.execute("""
                INSERT INTO dialogue_trees (title, topic, cefr_level)
                VALUES (?, ?, ?);
            """, (sc["title"], sc["topic"], sc["cefr_level"]))
            tree_id = cursor.lastrowid

            local_node_map = {}
            for node in sc["nodes"]:
                cursor.execute("""
                    INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (node["text_en"], node["text_vi"], 2.0, sc["cefr_level"], f"dialogue_tree_{tree_id}_node_{node['node_index']}.mp3", "DialogueTree"))

                cursor.execute("SELECT id FROM sentences WHERE text_en = ?;", (node["text_en"],))
                s_row = cursor.fetchone()
                sent_id = s_row[0] if s_row else 1

                parent_db_id = local_node_map.get(node.get("parent_index"))

                cursor.execute("""
                    INSERT INTO dialogue_nodes (tree_id, parent_node_id, sentence_id, speaker_role, choice_label)
                    VALUES (?, ?, ?, ?, ?);
                """, (tree_id, parent_db_id, sent_id, node["speaker_role"], node["choice_label"]))
                node_db_id = cursor.lastrowid
                local_node_map[node["node_index"]] = node_db_id
                nodes_count += 1

        conn.commit()
        logger.info("[Step 7] Completed: %s dialogue trees, %s nodes.", len(scenarios), nodes_count)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=len(scenarios))
```

Create `src/pipeline/steps/08_ipa_mapping.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.media.ipa_mapper import IPAMapper

logger = logging.getLogger(__name__)

class IPAMappingStep(BaseStep):
    name = "ipa_mapping"
    description = "Populate missing UK/US IPA transcriptions"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM words WHERE ipa_us IS NULL OR ipa_uk IS NULL;")
        missing = cursor.fetchone()[0]
        if missing == 0:
            return True, "100% of words already have IPA transcriptions."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 8] Mapping UK/US IPA transcriptions...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, lemma, ipa_uk, ipa_us FROM words WHERE ipa_us IS NULL OR ipa_uk IS NULL;")
        rows = cursor.fetchall()

        ipa_mapper = IPAMapper()
        updated = 0
        for w_id, lemma, existing_uk, existing_us in rows:
            uk = ipa_mapper.get_ipa(lemma, existing_ipa=existing_uk)
            us = ipa_mapper.get_ipa(lemma, existing_ipa=existing_us)
            cursor.execute("UPDATE words SET ipa_uk = ?, ipa_us = ? WHERE id = ?;", (uk, us, w_id))
            updated += 1

        conn.commit()
        logger.info("[Step 8] Completed: updated IPA for %s words.", f"{updated:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=updated)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_steps_05_08.py -v`
Expected: PASS with 1 test passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/ tests/test_pipeline_steps_05_08.py
git commit -m "feat(pipeline): implement step modules 05 through 08"
```

---

### Task 5: Steps 09–12 (Audio Generation, Phrase MWE, Lexical Relations, Vietnamese Backfill)

**Files:**
- Create: `src/pipeline/steps/09_audio_generation.py`
- Create: `src/pipeline/steps/10_phrase_mwe.py`
- Create: `src/pipeline/steps/11_relations_topics.py`
- Create: `src/pipeline/steps/12_vietnamese_backfill.py`
- Test: `tests/test_pipeline_steps_09_12.py`

**Interfaces:**
- Consumes: `BaseStep`, `PipelineContext`, `AudioGenerator`, `PhraseParser`, `PhraseGrader`, `PhraseExampleMatcher`, `RelationParser`, `Translator`, `VietnameseTextValidator`
- Produces: `AudioGenerationStep`, `PhraseMWEStep`, `RelationsTopicsStep`, `VietnameseBackfillStep`

- [ ] **Step 1: Write failing unit test for steps 09-12**

```python
# tests/test_pipeline_steps_09_12.py
import pytest
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.09_audio_generation import AudioGenerationStep
from src.pipeline.steps.10_phrase_mwe import PhraseMWEStep
from src.pipeline.steps.11_relations_topics import RelationsTopicsStep
from src.pipeline.steps.12_vietnamese_backfill import VietnameseBackfillStep


def test_relations_topics_skip_condition():
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # relations = 60000, topics = 1500, inverse = 5000
    mock_cursor.fetchone.side_effect = [(60000,), (1500,), (5000,)]

    mock_args = MagicMock()
    mock_args.force_reset = False
    ctx = PipelineContext(db_manager=mock_db, args=mock_args)
    step = RelationsTopicsStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "CHECKPOINT DETECTED" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_steps_09_12.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.steps.09_audio_generation'"

- [ ] **Step 3: Implement step modules 09 to 12**

Create `src/pipeline/steps/09_audio_generation.py`:
```python
import asyncio
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.media.audio_generator import AudioGenerator

logger = logging.getLogger(__name__)

class AudioGenerationStep(BaseStep):
    name = "audio_generation"
    description = "Generate dual-speed physical MP3 audio files via Edge-TTS"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Always runs sample audio check unless force-reset is explicitly passed or overridden
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 9] Generating Physical MP3 Audio Files via Edge-TTS...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        async def generate_sample_audio_files():
            audio_gen = AudioGenerator()
            cursor.execute("SELECT id, text_en FROM sentences LIMIT 100;")
            sents = cursor.fetchall()
            tasks = [audio_gen.generate_dual_speed_sentence(s_id, t_en) for s_id, t_en in sents]
            await asyncio.gather(*tasks)

        try:
            asyncio.run(generate_sample_audio_files())
            logger.info("   [Step 9] Generated physical MP3 audio files in data/audio/")
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=100)
        except Exception as e:
            logger.warning("   [Step 9] Audio generation warning: %s", e)
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0, message=str(e))
```

Create `src/pipeline/steps/10_phrase_mwe.py`:
```python
import asyncio
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.phrase_parser import PhraseParser
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.phrase_grader import PhraseGrader
from src.nlp.phrase_example_matcher import PhraseExampleMatcher
from src.nlp.translator import Translator
from src.media.audio_generator import AudioGenerator

logger = logging.getLogger(__name__)

class PhraseMWEStep(BaseStep):
    name = "phrase_mwe"
    description = "Ingest Multi-Word Expressions (idioms, phrasal verbs, proverbs)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM phrases;")
        existing_phrases = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM phrases WHERE audio_std IS NULL OR audio_fast IS NULL;")
        missing_audio = cursor.fetchone()[0]

        if existing_phrases > 500 and missing_audio == 0:
            return True, f"CHECKPOINT DETECTED: {existing_phrases:,} phrases with complete audio already exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 10] Ingesting Multi-Word Expressions...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

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
                context.db_manager.insert_phrases_batch(phrases_batch)
                phrase_count += len(phrases_batch)
                phrases_batch = []

        if phrases_batch:
            context.db_manager.insert_phrases_batch(phrases_batch)
            phrase_count += len(phrases_batch)

        cursor.execute("SELECT id, text_en, cefr_level FROM sentences;")
        sentence_pool = [{"id": r[0], "text_en": r[1], "cefr_level": r[2]} for r in cursor.fetchall()]
        matcher = PhraseExampleMatcher(sentence_pool)

        cursor.execute("SELECT id, phrase FROM phrases;")
        stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
        link_batch = matcher.match_phrases(stored_phrases)
        for i in range(0, len(link_batch), 5000):
            context.db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])

        async def generate_phrase_audio():
            audio_gen = AudioGenerator()
            for i in range(0, len(stored_phrases), 10):
                chunk = stored_phrases[i:i + 10]
                results = await asyncio.gather(
                    *[audio_gen.generate_dual_speed_phrase(item["id"], item["phrase"]) for item in chunk]
                )
                updates = []
                for item, res in zip(chunk, results):
                    status = "ok" if res["standard_path"] and res["fast_path"] else "failed"
                    updates.append((
                        str(res["standard_path"]) if res["standard_path"] else None,
                        str(res["fast_path"]) if res["fast_path"] else None,
                        status,
                        item["id"]
                    ))
                cursor.executemany("UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;", updates)
                conn.commit()

        try:
            asyncio.run(generate_phrase_audio())
        except Exception as e:
            logger.warning("   [Step 10] Phrase audio warning: %s", e)

        logger.info("[Step 10] Completed: %s phrases stored, %s links.", f"{phrase_count:,}", f"{len(link_batch):,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=phrase_count)
```

Create `src/pipeline/steps/11_relations_topics.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH
from src.ingestion.relation_parser import RelationParser

logger = logging.getLogger(__name__)

RELATION_CHECKPOINT = 50_000
TOPIC_CHECKPOINT = 1_000

class RelationsTopicsStep(BaseStep):
    name = "relations_topics"
    description = "Extract lexical relations (synonyms, antonyms) and 18 topic themes"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM word_relations;")
        existing_relations = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM word_topics;")
        existing_topics = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM word_relations WHERE inverted = 1;")
        existing_inverse = cursor.fetchone()[0]

        if existing_relations > RELATION_CHECKPOINT and existing_topics > TOPIC_CHECKPOINT and existing_inverse > 0:
            return True, f"CHECKPOINT DETECTED: {existing_relations:,} relations, {existing_topics:,} topics exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 11] Building Lexical Relations & Topics...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        relation_parser = RelationParser(KAIKKI_JSON_PATH)
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
                    context.db_manager.insert_word_relations_batch(relations_batch)
                    relation_count += len(relations_batch)
                    relations_batch = []
            for top in item["topics"]:
                topics_batch.append({"word_id": word_id, "topic": top["topic"], "raw_topic": top["raw_topic"]})
                if len(topics_batch) >= 1000:
                    context.db_manager.insert_word_topics_batch(topics_batch)
                    topics_count += len(topics_batch)
                    topics_batch = []

        if relations_batch:
            context.db_manager.insert_word_relations_batch(relations_batch)
            relation_count += len(relations_batch)
        if topics_batch:
            context.db_manager.insert_word_topics_batch(topics_batch)
            topics_count += len(topics_batch)

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
                context.db_manager.insert_word_relations_batch(inverse_batch)
                link_count += len(inverse_batch)
                inverse_batch = []
        if inverse_batch:
            context.db_manager.insert_word_relations_batch(inverse_batch)
            link_count += len(inverse_batch)

        logger.info("[Step 11] Completed: %s relations, %s inverse links, %s topics.", f"{relation_count:,}", f"{link_count:,}", f"{topics_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=relation_count + topics_count + link_count)
```

Create `src/pipeline/steps/12_vietnamese_backfill.py`:
```python
import time
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.translator import Translator
from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)

VI_BATCH_SLEEP_SECONDS = 0.1
VI_TRANSLATION_BUDGET = 1000

class VietnameseBackfillStep(BaseStep):
    name = "vietnamese_backfill"
    description = "Validate & backfill Vietnamese translations with budget capping"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM definitions WHERE definition_vi IS NULL OR definition_vi = '';")
        def_missing = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        col_missing = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        phrase_missing = cursor.fetchone()[0]

        if (def_missing + col_missing + phrase_missing) == 0:
            return True, "No missing Vietnamese translations remain."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 12] Backfilling Vietnamese translations...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
        conn.commit()

        cursor.execute("""
            SELECT d.id, d.definition_en FROM definitions d
            JOIN words w ON w.id = d.word_id
            WHERE d.definition_vi IS NULL OR d.definition_vi = ''
            ORDER BY (w.cefr_level IS NULL), d.id;
        """)
        priority_definitions = cursor.fetchall()
        cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        priority_collocations = cursor.fetchall()
        cursor.execute("SELECT id, definition_en FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        priority_phrases = cursor.fetchall()

        translator = Translator()
        validator = VietnameseTextValidator()
        budget = getattr(context.args, "vi_budget", VI_TRANSLATION_BUDGET)

        colloc_budget = 0
        phrase_budget = 0
        defs_budget = 0
        if budget >= 3:
            small_table_slice = max(1, budget // 10)
            colloc_budget = min(len(priority_collocations), small_table_slice)
            phrase_budget = min(len(priority_phrases), small_table_slice)
            defs_budget = max(0, budget - colloc_budget - phrase_budget)
        elif budget > 0:
            colloc_budget = min(len(priority_collocations), budget)

        def _backfill(rows, table, id_col, target_col, remaining_budget):
            updated = 0
            for batch_start in range(0, len(rows), 1000):
                if remaining_budget <= 0:
                    break
                batch = rows[batch_start:batch_start + 1000]
                updates = []
                for row_id, text in batch:
                    if remaining_budget <= 0:
                        break
                    remaining_budget -= 1
                    vi = translator.translate_text(text)
                    if vi and validator.is_vietnamese(vi):
                        updates.append((vi, row_id))
                if updates:
                    cursor.executemany(f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?;", updates)
                    conn.commit()
                    updated += len(updates)
                time.sleep(VI_BATCH_SLEEP_SECONDS)
            return updated, remaining_budget

        translated_defs, _ = _backfill(priority_definitions, "definitions", "id", "definition_vi", defs_budget)
        translated_colls, _ = _backfill(priority_collocations, "collocations", "id", "meaning_vi", colloc_budget)
        translated_phrases, _ = _backfill(priority_phrases, "phrases", "id", "definition_vi", phrase_budget)

        logger.info("[Step 12] Completed: translated %s defs, %s colls, %s phrases.", f"{translated_defs:,}", f"{translated_colls:,}", f"{translated_phrases:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=translated_defs + translated_colls + translated_phrases)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_steps_09_12.py -v`
Expected: PASS with 1 test passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/ tests/test_pipeline_steps_09_12.py
git commit -m "feat(pipeline): implement step modules 09 through 12"
```

---

### Task 6: Steps 13–15 (Core Pack, Sentence Coverage, SQLite Export)

**Files:**
- Create: `src/pipeline/steps/13_core_pack.py`
- Create: `src/pipeline/steps/14_sentence_coverage.py`
- Create: `src/pipeline/steps/15_sqlite_export.py`
- Test: `tests/test_pipeline_steps_13_15.py`

**Interfaces:**
- Consumes: `BaseStep`, `PipelineContext`, `CorePackBuilder`, `ParallelCorpusParser`, `SentenceFilter`, `SQLiteExporter`
- Produces: `CorePackStep`, `SentenceCoverageStep`, `SQLiteExportStep`

- [ ] **Step 1: Write failing unit test for steps 13-15**

```python
# tests/test_pipeline_steps_13_15.py
import pytest
from unittest.mock import MagicMock

from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.13_core_pack import CorePackStep
from src.pipeline.steps.14_sentence_coverage import SentenceCoverageStep
from src.pipeline.steps.15_sqlite_export import SQLiteExportStep


def test_core_pack_skip_condition():
    mock_args = MagicMock()
    mock_args.build_core_pack = False

    ctx = PipelineContext(db_manager=MagicMock(), args=mock_args)
    step = CorePackStep()

    skip, reason = step.should_skip(ctx)
    assert skip
    assert "--build-core-pack flag NOT set" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_steps_13_15.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.steps.13_core_pack'"

- [ ] **Step 3: Implement step modules 13 to 15**

Create `src/pipeline/steps/13_core_pack.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import EXPORT_SQLITE_PATH, OUTPUT_DIR, NGSL_PATH, SUBTLEX_FREQ_PATH
from src.nlp.cefr_grader import CEFRGrader
from src.export.core_pack_builder import CorePackBuilder

logger = logging.getLogger(__name__)

class CorePackStep(BaseStep):
    name = "core_pack"
    description = "Curate and export Core 3000 Pack (core_3000.db)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if not getattr(context.args, "build_core_pack", False):
            return True, "Flag --build-core-pack NOT set."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 13] Building Core 3000 Word Pack...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        freq_dict = dict(grader.freq_dict)

        pack_dir = OUTPUT_DIR / "core_pack"
        builder = CorePackBuilder(source_db_path=EXPORT_SQLITE_PATH, output_dir=pack_dir)
        vi_budget = getattr(context.args, "vi_budget", 1000)
        report = builder.build(freq_dict=freq_dict, ngsl_path=NGSL_PATH, vi_budget=vi_budget)

        logger.info("[Step 13] Core pack built: %s words, pass rate %.1f%%.", f"{report['selected']:,}", report["pass_rate"] * 100)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=report["selected"], metrics=report)
```

Create `src/pipeline/steps/14_sentence_coverage.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import (
    ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
    ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    MAX_SENTENCES_PER_CORPUS, OPENSUBTITLES_EN, OPENSUBTITLES_VI,
    SUBTLEX_FREQ_PATH
)
from src.ingestion.opus_parser import ParallelCorpusParser
from src.ingestion.sentence_filter import SentenceFilter
from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)

class SentenceCoverageStep(BaseStep):
    name = "sentence_coverage"
    description = "Ingest OPUS & EnViCorpora parallel sentence coverage"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Step handles corpus-by-corpus skipping internally
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 14] Ingesting Sentence Coverage Parallel Corpora...")
        corpora = [
            (OPENSUBTITLES_EN, OPENSUBTITLES_VI, "OpenSubtitles"),
            (ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
            (ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, "Basic-EnVi"),
        ]
        sf = SentenceFilter()
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)

        inserted_total = 0
        for en_path, vi_path, source in corpora:
            if not en_path.exists() or not vi_path.exists():
                logger.info("   [SentenceCoverage] %s corpus missing — skipping.", source)
                continue
            existing = context.db_manager.count_sentences_by_source(source)
            if existing > 0 and not getattr(context.args, "force_reset", False):
                logger.info("   [SentenceCoverage] %s already ingested (%s rows) — skipping.", source, f"{existing:,}")
                continue

            batch, inserted = [], 0
            for pair in ParallelCorpusParser(en_path, vi_path, source=source).parse_pairs():
                if inserted + len(batch) >= MAX_SENTENCES_PER_CORPUS:
                    break
                if not sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
                    continue
                graded = grader.grade_sentence(pair["text_en"])
                batch.append({
                    "text_en": pair["text_en"],
                    "text_vi": pair["text_vi"],
                    "difficulty_score": graded["difficulty_score"],
                    "cefr_level": graded["cefr_level"],
                    "audio_path": None,
                    "source": source,
                })
                if len(batch) >= 5000:
                    context.db_manager.insert_sentences_batch(batch)
                    inserted += len(batch)
                    batch = []
            if batch:
                context.db_manager.insert_sentences_batch(batch)
                inserted += len(batch)
            inserted_total += inserted

        logger.info("[Step 14] Completed: %s new sentences inserted.", f"{inserted_total:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=inserted_total)
```

Create `src/pipeline/steps/15_sqlite_export.py`:
```python
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import EXPORT_SQLITE_PATH
from src.export.sqlite_exporter import SQLiteExporter

logger = logging.getLogger(__name__)

class SQLiteExportStep(BaseStep):
    name = "sqlite_export"
    description = "Build composite indexes, enable WAL mode, and export optimized SQLite DB"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 15] Packaging & Optimizing SQLite Mobile Database...")
        exporter = SQLiteExporter(EXPORT_SQLITE_PATH)
        export_info = exporter.optimize_and_package()
        avg_speed = exporter.benchmark_reflex_query_speed(iterations=20)
        logger.info("   -> Reflex Query Benchmark Speed: %.2f ms", avg_speed)

        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=1,
            metrics={"size_mb": export_info["size_mb"], "reflex_speed_ms": avg_speed}
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_steps_13_15.py -v`
Expected: PASS with 1 test passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/steps/ tests/test_pipeline_steps_13_15.py
git commit -m "feat(pipeline): implement step modules 13 through 15"
```

---

### Task 7: CLI Argument Parser & Default Registry Loader

**Files:**
- Create: `src/pipeline/cli.py`
- Modify: `src/pipeline/core/registry.py`
- Test: `tests/test_pipeline_cli.py`

**Interfaces:**
- Consumes: `argparse`, `StepRegistry`, Step Modules 01–15
- Produces: `parse_arguments()`, `get_default_registry()`

- [ ] **Step 1: Write failing unit test for CLI and default registry**

```python
# tests/test_pipeline_cli.py
import pytest
from src.pipeline.cli import parse_arguments
from src.pipeline.core.registry import get_default_registry


def test_cli_argument_parser():
    args = parse_arguments(["--steps", "schema_init,phrase_mwe", "--dry-run", "--vi-budget", "500"])
    assert args.steps == "schema_init,phrase_mwe"
    assert args.dry_run is True
    assert args.vi_budget == 500


def test_default_registry_loading():
    reg = get_default_registry()
    steps = reg.get_all_steps()
    assert len(steps) == 15
    names = [s.name for s in steps]
    assert names[0] == "schema_init"
    assert names[-1] == "sqlite_export"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_cli.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.pipeline.cli'"

- [ ] **Step 3: Implement CLI parser and default registry loader**

Create `src/pipeline/cli.py`:
```python
import argparse
from typing import List, Optional

def parse_arguments(args_list: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Vocab Craft Engine Pipeline Runner")
    parser.add_argument("--steps", type=str, help="Comma-separated step names to execute (e.g. schema_init,phrase_mwe).")
    parser.add_argument("--skip-steps", type=str, help="Comma-separated step names to skip.")
    parser.add_argument("--dry-run", action="store_true", help="Preview step execution plan without modifying database.")
    parser.add_argument("--force-reset", action="store_true", help="Force complete database reset and re-ingest everything.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Kaikki dictionary ingestion step.")
    parser.add_argument("--vi-budget", type=int, default=1000, help="Max MT translation attempts for Vietnamese backfill.")
    parser.add_argument("--build-core-pack", action="store_true", help="Build the curated Core 3000 word pack.")
    return parser.parse_args(args_list)
```

Modify `src/pipeline/core/registry.py` to add `get_default_registry()`:
```python
from typing import List, Dict, Optional
from src.pipeline.core.base_step import BaseStep

class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []
        self._step_map: Dict[str, BaseStep] = {}

    def register(self, step: BaseStep) -> None:
        self._steps.append(step)
        self._step_map[step.name] = step

    def get_all_steps(self) -> List[BaseStep]:
        return list(self._steps)

    def get_step(self, name: str) -> Optional[BaseStep]:
        return self._step_map.get(name)

    def filter_steps(
        self,
        include_steps: Optional[List[str]] = None,
        skip_steps: Optional[List[str]] = None
    ) -> List[BaseStep]:
        steps = list(self._steps)
        if include_steps:
            inc_set = set(include_steps)
            steps = [s for s in steps if s.name in inc_set]
        if skip_steps:
            skip_set = set(skip_steps)
            steps = [s for s in steps if s.name not in skip_set]
        return steps

def get_default_registry() -> StepRegistry:
    from src.pipeline.steps import (
        SchemaInitStep,
        KaikkiIngestionStep,
        TatoebaIngestionStep,
        SentenceLinkingStep,
        NLPEnrichmentStep,
        ReflexDrillsStep,
        ScenarioTreesStep,
        IPAMappingStep,
        AudioGenerationStep,
        PhraseMWEStep,
        RelationsTopicsStep,
        VietnameseBackfillStep,
        CorePackStep,
        SentenceCoverageStep,
        SQLiteExportStep
    )

    registry = StepRegistry()
    registry.register(SchemaInitStep())
    registry.register(KaikkiIngestionStep())
    registry.register(TatoebaIngestionStep())
    registry.register(SentenceLinkingStep())
    registry.register(NLPEnrichmentStep())
    registry.register(ReflexDrillsStep())
    registry.register(ScenarioTreesStep())
    registry.register(IPAMappingStep())
    registry.register(AudioGenerationStep())
    registry.register(PhraseMWEStep())
    registry.register(RelationsTopicsStep())
    registry.register(VietnameseBackfillStep())
    registry.register(CorePackStep())
    registry.register(SentenceCoverageStep())
    registry.register(SQLiteExportStep())
    return registry
```

Update `src/pipeline/steps/__init__.py` to expose all step classes cleanly:
```python
import importlib

SchemaInitStep = importlib.import_module("src.pipeline.steps.01_schema_init").SchemaInitStep
KaikkiIngestionStep = importlib.import_module("src.pipeline.steps.02_kaikki_ingestion").KaikkiIngestionStep
TatoebaIngestionStep = importlib.import_module("src.pipeline.steps.03_tatoeba_ingestion").TatoebaIngestionStep
SentenceLinkingStep = importlib.import_module("src.pipeline.steps.04_sentence_linking").SentenceLinkingStep
NLPEnrichmentStep = importlib.import_module("src.pipeline.steps.05_nlp_enrichment").NLPEnrichmentStep
ReflexDrillsStep = importlib.import_module("src.pipeline.steps.06_reflex_drills").ReflexDrillsStep
ScenarioTreesStep = importlib.import_module("src.pipeline.steps.07_scenario_trees").ScenarioTreesStep
IPAMappingStep = importlib.import_module("src.pipeline.steps.08_ipa_mapping").IPAMappingStep
AudioGenerationStep = importlib.import_module("src.pipeline.steps.09_audio_generation").AudioGenerationStep
PhraseMWEStep = importlib.import_module("src.pipeline.steps.10_phrase_mwe").PhraseMWEStep
RelationsTopicsStep = importlib.import_module("src.pipeline.steps.11_relations_topics").RelationsTopicsStep
VietnameseBackfillStep = importlib.import_module("src.pipeline.steps.12_vietnamese_backfill").VietnameseBackfillStep
CorePackStep = importlib.import_module("src.pipeline.steps.13_core_pack").CorePackStep
SentenceCoverageStep = importlib.import_module("src.pipeline.steps.14_sentence_coverage").SentenceCoverageStep
SQLiteExportStep = importlib.import_module("src.pipeline.steps.15_sqlite_export").SQLiteExportStep

__all__ = [
    "SchemaInitStep",
    "KaikkiIngestionStep",
    "TatoebaIngestionStep",
    "SentenceLinkingStep",
    "NLPEnrichmentStep",
    "ReflexDrillsStep",
    "ScenarioTreesStep",
    "IPAMappingStep",
    "AudioGenerationStep",
    "PhraseMWEStep",
    "RelationsTopicsStep",
    "VietnameseBackfillStep",
    "CorePackStep",
    "SentenceCoverageStep",
    "SQLiteExportStep",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_cli.py -v`
Expected: PASS with 2 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/cli.py src/pipeline/core/registry.py src/pipeline/steps/__init__.py tests/test_pipeline_cli.py
git commit -m "feat(pipeline): add CLI argument parsing and default 15-step registry loader"
```

---

### Task 8: Refactor `main.py` Entrypoint & Full Integration Verification

**Files:**
- Modify: `main.py`
- Test: Run full `pytest` suite and dry-run execution test

**Interfaces:**
- Consumes: `parse_arguments`, `PipelineContext`, `PipelineOrchestrator`, `get_default_registry`, `DatabaseManager`
- Produces: Refactored clean ~30-line `main.py`

- [ ] **Step 1: Write integration test verifying main entrypoint with dry-run**

```python
# tests/test_pipeline_integration.py
import subprocess
import pytest

def test_pipeline_dry_run_cli():
    result = subprocess.run(
        ["python", "main.py", "--dry-run"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "[DRY-RUN] Would run 'schema_init'" in result.stdout or "[DRY-RUN] Would run 'schema_init'" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails before main.py update**

Run: `pytest tests/test_pipeline_integration.py -v`
Expected: FAIL (or output missing dry-run logs because old `main.py` does not support `--dry-run`)

- [ ] **Step 3: Update `main.py` to delegate orchestration to `PipelineOrchestrator`**

Replace contents of `main.py` with:
```python
"""
Main Execution Pipeline for English Dataset System Engine.
Orchestrates Ingestion, NLP Enrichment, Collocation Extraction, Dialogue Trees, Reflex Drill Generation, and SQLite Export.
Now modularized via src.pipeline steps & orchestrator.
"""

import sys
import logging
from src.pipeline.cli import parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry
from src.db.staging_db import DatabaseManager
from config.settings import EXPORT_SQLITE_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def main():
    args = parse_arguments()
    db_manager = DatabaseManager(db_path=EXPORT_SQLITE_PATH)
    context = PipelineContext(db_manager=db_manager, args=args)

    registry = get_default_registry()
    orchestrator = PipelineOrchestrator(registry=registry)

    summary = orchestrator.run(context)
    if summary.has_failures:
        logger.error("Pipeline failed with error(s).")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run integration test and existing test suite to verify all pass**

Run: `pytest -v`
Expected: ALL PASS cleanly.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_pipeline_integration.py
git commit -m "refactor(main): switch main.py entrypoint to use PipelineOrchestrator"
```

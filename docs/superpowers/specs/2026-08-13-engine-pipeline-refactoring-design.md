# Engine Pipeline Refactoring Design Specification

**Date:** 2026-08-13  
**Status:** Approved  
**Target Component:** `vocab-craft-engine` Core Pipeline Runner & Orchestration Engine  

---

## 1. Executive Summary & Goals

### 1.1 Context & Problem Statement
Currently, the entire execution flow of the `vocab-craft-engine` pipeline is contained within a monolithic ~900-line script (`main.py`). All ingestion steps, NLP enrichment, collocation extraction, dialogue trees, reflex drills, TTS audio generation, phrase step, relation/topic step, translation backfill, core pack curation, and mobile SQLite packaging logic are mixed together with raw CLI argument parsing, ad-hoc checkpoint checks, and database management.

This monolithic layout makes it difficult to:
- **Debug & Isolate:** Running or testing a single sub-step (e.g., phrase ingestion or Vietnamese translation backfill) requires re-running or manual script modifications.
- **Observe:** Lack of unified progress tracking, metrics logging, and clear execution summary reporting.
- **Maintain & Extend:** Adding a new pipeline feature or step risks breaking adjacent steps due to shared global variables and tangled context.

### 1.2 Architectural Goals
1. **Decoupled Step Architecture:** Refactor the monolith into single-responsibility step modules conforming to a `BaseStep` interface.
2. **Unified Pipeline Context & State Management:** Pass environment state, DB connection, CLI options, and step metrics cleanly via a `PipelineContext` and track step lifecycle in a centralized `StateManager`.
3. **Flexible CLI & Orchestration:** Enable full or selective step execution (`--steps`, `--skip-steps`), dry-run mode (`--dry-run`), and clean checkpoint auto-resuming.
4. **Enhanced Observability:** Provide a structured terminal summary report detailing step status (`SUCCESS`, `SKIPPED`, `FAILED`), execution duration, and items processed.

---

## 2. System Architecture & Core Interfaces

The refactored pipeline is located under `src/pipeline/`:

```
src/pipeline/
├── core/
│   ├── base_step.py          # BaseStep abstract base class
│   ├── context.py            # PipelineContext data container
│   ├── result.py             # StepResult and StepStatus enums
│   ├── state_manager.py      # Execution metrics and checkpoint logging
│   ├── registry.py           # StepRegistry for registering/retrieving steps
│   └── orchestrator.py       # PipelineOrchestrator execution engine
├── steps/                    # 15 individual pipeline step modules
│   ├── 01_schema_init.py
│   ├── 02_kaikki_ingestion.py
│   ├── 03_tatoeba_ingestion.py
│   ├── 04_sentence_linking.py
│   ├── 05_nlp_enrichment.py
│   ├── 06_reflex_drills.py
│   ├── 07_scenario_trees.py
│   ├── 08_ipa_mapping.py
│   ├── 09_audio_generation.py
│   ├── 10_phrase_mwe.py
│   ├── 11_relations_topics.py
│   ├── 12_vietnamese_backfill.py
│   ├── 13_core_pack.py
│   ├── 14_sentence_coverage.py
│   └── 15_sqlite_export.py
└── cli.py                    # CLI argument parser & runner setup
```

### 2.1 Core Interfaces

#### `BaseStep` (`src/pipeline/core/base_step.py`)
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
        """Determines whether to skip execution (e.g. database checkpoint exists or flag active)."""
        pass

    @abstractmethod
    def run(self, context: PipelineContext) -> StepResult:
        """Executes the core step logic."""
        pass

    def rollback(self, context: PipelineContext) -> None:
        """Optional cleanup routine if step execution fails."""
        pass
```

#### `PipelineContext` (`src/pipeline/core/context.py`)
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

#### `StepResult` & `StepStatus` (`src/pipeline/core/result.py`)
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

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
```

#### `StateManager` (`src/pipeline/core/state_manager.py`)
Tracks run metadata in `.pipeline_state.json` and staging DB to record step execution history, runtime durations, and processed item counts.

---

## 3. Step Decomposition & Pipeline Flow

The 15 steps decomposed from `main.py` are executed in the following strict order:

| Step Name | Module File | Primary Purpose | Skip Condition (`should_skip`) |
|---|---|---|---|
| `schema_init` | `01_schema_init.py` | Init SQLite DB schema & handle `--force-reset` wipe | Never skipped |
| `kaikki_ingestion` | `02_kaikki_ingestion.py` | Ingest 3.18GB Kaikki Wiktionary dump | `words > 10,000` & `defs > 10,000` OR `--skip-dict` |
| `tatoeba_ingestion` | `03_tatoeba_ingestion.py` | Ingest Tatoeba parallel sentences | `sentences > 1,000` |
| `sentence_linking` | `04_sentence_linking.py` | Link words to sentences | `.sentence_link_checkpoint.json` present |
| `nlp_enrichment` | `05_nlp_enrichment.py` | Extract collocations & sentence patterns | Collocations & patterns exist in DB |
| `reflex_drills` | `06_reflex_drills.py` | Generate speed reflex cards (< 2.5s) | `reflex_drills > 0` |
| `scenario_trees` | `07_scenario_trees.py` | Build branching dialogue trees | `dialogue_trees > 0` |
| `ipa_mapping` | `08_ipa_mapping.py` | Populate UK/US IPA transcriptions | 100% words populated |
| `audio_generation` | `09_audio_generation.py` | Synthesize Edge-TTS 1.0x/1.2x MP3 audio | Complete audio files exist |
| `phrase_mwe` | `10_phrase_mwe.py` | Ingest Idioms, Phrasal Verbs, Proverbs | `phrases > 500` & audio complete |
| `relations_topics` | `11_relations_topics.py` | Extract Synonyms, Antonyms, 18 Themes | Checkpoint record count > target |
| `vietnamese_backfill` | `12_vietnamese_backfill.py` | Validate & backfill VI translations | No missing defs OR `--vi-budget` met |
| `core_pack` | `13_core_pack.py` | Curate Core 3000 Pack (`core_3000.db`) | Flag `--build-core-pack` NOT set |
| `sentence_coverage` | `14_sentence_coverage.py` | Ingest OPUS & EnViCorpora dialogues | Extended sentence threshold met |
| `sqlite_export` | `15_sqlite_export.py` | Build composite indexes, WAL mode, export DB | Target `english_dataset.db` optimized |

---

## 4. CLI Interface & Orchestrator Design

### 4.1 CLI Arguments (`src/pipeline/cli.py`)
- `--steps STEP1,STEP2`: Run only specified steps (e.g. `--steps phrase_mwe,vietnamese_backfill`).
- `--skip-steps STEP1,STEP2`: Skip specified steps (e.g. `--skip-steps audio_generation`).
- `--dry-run`: Preview step execution plan and skip checks without modifying database state.
- `--force-reset`: Re-initialize database schema and clear checkpoints.
- `--skip-dict`: Skip Kaikki dictionary ingestion step.
- `--vi-budget INT`: Limit max machine translation calls for backfill step.
- `--build-core-pack`: Trigger creation of the Core 3000 pack database.

### 4.2 Pipeline Entrypoint (`main.py`)
```python
import sys
from src.pipeline.cli import parse_arguments
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry
from src.db.staging_db import DatabaseManager
from config.settings import EXPORT_SQLITE_PATH

def main():
    args = parse_arguments()
    db_manager = DatabaseManager(db_path=EXPORT_SQLITE_PATH)
    context = PipelineContext(db_manager=db_manager, args=args)
    
    registry = get_default_registry()
    orchestrator = PipelineOrchestrator(registry=registry)
    
    summary = orchestrator.run(context)
    if summary.has_failures:
        sys.exit(1)

if __name__ == "__main__":
    main()
```

---

## 5. Verification & Testing Strategy

1. **Unit Testing:**
   - Test `BaseStep` contract and subclass implementation behavior.
   - Test `PipelineContext` state passing and `StepRegistry` filtering logic.
   - Test `PipelineOrchestrator` execution with mocked steps.

2. **Integration Testing:**
   - Run pipeline in `--dry-run` mode to verify step registration and skip conditions.
   - Execute specific steps via `--steps` (e.g. `schema_init`, `phrase_mwe`) against an isolated test database to verify correctness.

# Pipeline Violations Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all verified pipeline violations across pipeline core modules, steps 01-14, and integration tests to ensure strict accuracy, idempotency, memory efficiency, and state isolation.

**Architecture:** 
- Fix core components (`StepRegistry`, `StateManager`, `PipelineOrchestrator`, `test_pipeline_integration.py`) to properly validate CLI inputs, clear run state on execution, and isolate test side-effects.
- Fix step skip conditions and checkpoints in steps 01, 03, 04, 06, 09, 10, 11, 12, 13, 14 to use accurate SQL queries, prevent premature skips, handle empty data/failures properly, avoid memory bloat, and maintain atomic DB transactions.

**Tech Stack:** Python 3.10+, SQLite3, pytest, asyncio.

---

### Task 1: Core Framework & Test Hermeticity Fixes

**Files:**
- Modify: `src/pipeline/core/registry.py`
- Modify: `src/pipeline/core/state_manager.py`
- Modify: `src/pipeline/core/orchestrator.py`
- Modify: `tests/test_pipeline_integration.py`
- Test: `tests/test_pipeline_core.py`, `tests/test_pipeline_orchestrator.py`, `tests/test_pipeline_integration.py`

**Steps:**
- [ ] Validate unknown step names in `skip_steps` within `StepRegistry.filter_steps()`.
- [ ] Add `clear_state()` to `StateManager` to reset `.pipeline_state.json`.
- [ ] Call `self.state_manager.clear_state()` in `PipelineOrchestrator.run()` when not in `dry_run` mode.
- [ ] Update `tests/test_pipeline_integration.py` to run inside pytest `tmp_path` / isolated working directory so running integration tests leaves no side effects in repo root.
- [ ] Run pytest to verify core tests pass.

---

### Task 2: Ingestion & Linking Step Fixes (Steps 01, 03, 04)

**Files:**
- Modify: `src/pipeline/steps/01_schema_init.py`
- Modify: `src/pipeline/steps/03_tatoeba_ingestion.py`
- Modify: `src/pipeline/steps/04_sentence_linking.py`
- Test: `tests/test_pipeline_steps_01_04.py`

**Steps:**
- [ ] In `01_schema_init.py`: Check `context.db_manager.db_path.exists()` instead of global `EXPORT_SQLITE_PATH.exists()`; add `"phrase_sentences"` and `"phrases"` to `tables_to_drop`.
- [ ] In `03_tatoeba_ingestion.py`: Count `source = 'Tatoeba'` for Tatoeba `should_skip` checkpoint; set `"audio_path": None` on insertion.
- [ ] In `04_sentence_linking.py`: Deduplicate `word_id`s per sentence in `_link_sentences_incrementally` before inserting into `map_batch`.
- [ ] Run pytest to verify steps 01-04 tests pass.

---

### Task 3: Enrichment & Drills Step Fixes (Steps 06, 09, 11)

**Files:**
- Modify: `src/pipeline/steps/06_reflex_drills.py`
- Modify: `src/pipeline/steps/09_audio_generation.py`
- Modify: `src/pipeline/steps/11_relations_topics.py`
- Test: `tests/test_pipeline_steps_05_08.py`, `tests/test_pipeline_steps_09_12.py`, `tests/test_relations_pipeline.py`

**Steps:**
- [ ] In `06_reflex_drills.py`: Update `should_skip` query to `SELECT COUNT(DISTINCT sentence_id) FROM reflex_drills WHERE drill_type = 'speed_translation'`; skip drill generation if `correct_answer` is empty/None; restrict delete to `DELETE FROM reflex_drills WHERE drill_type = 'speed_translation'`.
- [ ] In `09_audio_generation.py`: Re-raise exceptions in `except Exception as e:` so step failures propagate to orchestrator.
- [ ] In `11_relations_topics.py`: Update `should_skip` checkpoint to verify `inverse_hyponym_count >= natural_hypernym_count` (with `natural_hypernym_count > 0`); use `max(0, inserted)` when accumulating counts from batch inserts.
- [ ] Run pytest to verify steps 05-08 and 09-12 tests pass.

---

### Task 4: MWE, Backfill, Core Pack & Coverage Step Fixes (Steps 10, 12, 13, 14)

**Files:**
- Modify: `src/pipeline/steps/10_phrase_mwe.py`
- Modify: `src/pipeline/steps/12_vietnamese_backfill.py`
- Modify: `src/pipeline/steps/13_core_pack.py`
- Modify: `src/pipeline/steps/14_sentence_coverage.py`
- Test: `tests/test_pipeline_steps_09_12.py`, `tests/test_pipeline_steps_13_15.py`, `tests/test_sentence_coverage_pipeline.py`

**Steps:**
- [ ] In `10_phrase_mwe.py`: Validate recorded audio paths exist on disk and have size > 0 in `should_skip()`; skip parsing 3.18GB Kaikki dump if phrases already exist (>500); save translator cache after phrase translation; stream/batch sentence fetching during phrase matching; re-raise audio generation exception on error.
- [ ] In `12_vietnamese_backfill.py`: Make `should_skip()` query side-effect-free by checking `definition_vi = definition_en` / `meaning_vi = phrase` in the SQL count predicate instead of updating DB during skip check.
- [ ] In `13_core_pack.py`: Check if `freq_dict` is empty and raise `RuntimeError` before invoking `CorePackBuilder`.
- [ ] In `14_sentence_coverage.py`: Delete existing sentences for corpus source when `force_reset` is active; check `existing >= max_sentences` in skip check; track inserted row count correctly.
- [ ] Run full pytest suite to verify all 200+ tests pass.

# Lossless Scalable Lexical Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import every rank-1–3500 definition and its complete source evidence without duplicating linked sentence text per definition.

**Architecture:** Add snapshot-scoped immutable source evidence and word-link tables. The importer first streams source sentence links into those tables, then writes compact per-definition raw records. The evidence repository joins virtual linked examples at read time and persists only the selection/audit state required for a definition.

**Tech Stack:** Python, DuckDB, SQLite, Pydantic, pytest, Black, Ruff.

---

### Task 1: Add normalized source-evidence schema and catalog API

**Files:** `src/learning/schema.py`, `src/learning/catalog.py`, `tests/test_learning/test_schema.py`, `tests/test_learning/test_catalog.py`

- [x] Write RED tests that require `lexical_source_evidence` and `lexical_word_evidence_links`, reject a non-positive word/source ID, and prove repeated batch insertion retains one source value and one word link.
- [x] Add forward migration 007, table/index registration, and typed `SourceEvidenceLinkInput` catalog input. Generate a deterministic ID from snapshot, role, table, row ID, and canonical value SHA so batch retries need no lookup.
- [x] Run focused schema/catalog tests; commit `feat(learning): normalize lexical source evidence`.

### Task 2: Stream normalized evidence before compact definitions

**Files:** `src/learning/sqlite_reference_importer.py`, `src/learning/catalog.py`, `tests/test_learning/test_sqlite_reference_importer.py`, `tests/test_learning/test_catalog.py`

- [x] Write RED test for two definitions on one word with five linked sentences: five source evidence rows and five word links, compact definition payloads with no linked sentence text, and idempotent 251-row batching.
- [x] Stream materialized `word_sentences` in `IMPORT_BATCH_SIZE` batches into the new catalog API. Refactor ranked definition construction to retain definition/translation/IPA evidence and only an example-scope reference by word ID.
- [x] Update report metadata with source link/evidence counts; run focused importer/catalog tests; commit `feat(learning): stream normalized lexical examples`.

### Task 3: Resolve virtual examples during remediation

**Files:** `src/learning/lexical_evidence.py`, `src/learning/lexical_remediation.py`, `tests/test_learning/test_lexical_evidence.py`, `tests/test_learning/test_lexical_remediation.py`

- [x] Write RED test that two inputs for one word each receive the complete joined examples, but a selected virtual evidence item is the only virtual ranking row persisted for the run.
- [x] Extend `get_input` to join source evidence through word links and create input-scoped `EvidenceItem` views. Persist local rankings and selected virtual rankings; record a deterministic evidence inventory fingerprint and count in remediation rationale.
- [x] Run focused evidence/remediation tests; commit `feat(learning): resolve normalized lexical examples`.

### Task 4: Update the run contract and verify end-to-end

**Files:** `src/learning/lexical_reporting.py`, `docs/learning-graph-operations.md`, `tests/test_learning/test_lexical_reporting.py`, `tests/test_learning/test_lexical_53k_contract.py`

- [x] Write RED tests requiring manifest/report link counts and source-count reconciliation, using the actual observed count supplied by the importer rather than a hardcoded historical count.
- [x] Implement deterministic manifest/report fields and update operations documentation with the manifest-driven count contract and normalized evidence inventory.
- [x] Run `pytest tests/test_learning/ -v`, Black/Ruff changed files, and `make test`; commit `docs(learning): operate lossless lexical evidence imports`.

### Task 5: Stream virtual source selection and migrate legacy imports

**Files:** `src/learning/lexical_evidence.py`, `src/learning/lexical_remediation.py`, `src/learning/schema.py`, `src/learning/catalog.py`, and matching tests.

- [ ] Add a stress regression proving source examples are fetched/selected in bounded batches, without a per-definition list or serialized evidence-ID fan-out.
- [ ] Preserve word-link rank in the source evidence view and enforce that every persisted source ranking is linked to the input's snapshot and word.
- [ ] Add a forward migration/backfill or an explicitly versioned re-import path for pre-normalized lexical inputs, then verify it cannot mix legacy local examples with virtual examples.

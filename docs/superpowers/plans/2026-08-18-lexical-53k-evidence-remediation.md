# Lexical 53k Evidence-Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process every one of the 53,270 source definition rows whose word has
frequency rank 1–3,500 into an immutable, evidence-backed remediation graph.
The system must select only existing source evidence, explain every decision,
maintain a recoverable quarantine queue, and be ready to export a new,
backend-facing `english_dataset_verified_v1.db` once the deferred AI approval
stage has supplied approvals.

**Architecture:** `data/output/english_dataset.db` is a read-only reference,
never a destination. First materialize its current SQLite/WAL state to a
private, hash-addressed snapshot. Import one raw graph record per source
definition (not one bundle per word) and preserve every source alternative as
an evidence item. A deterministic remediation run ranks and selects evidence,
persists every selected/rejected alternative and disposition, and writes only
`validated`, `quarantined`, or `rejected`; it cannot manufacture `approved`.
The existing candidate/revision lifecycle remains the sole approval mechanism.
The final release builder selects only approved senses and refuses to create a
release until the release bar reconciles every input.

**Tech Stack:** Python 3.14, DuckDB, SQLite, Pydantic, pytest, Black, Ruff.

---

## Delivery boundary

This implementation deliberately creates the evidence/remediation foundation
and the guarded release builder; it does **not** implement the later AI
adjudicator. Therefore the full 53k execution will produce an auditable
pre-release and a durable quarantine database, but must not falsely label a
dataset `verified_v1` before all required approval/rejection decisions exist.

The eventual immutable release directory is:

```text
data/output/lexical-releases/english_dataset_verified_v1/
├── english_dataset_verified_v1.db   # backend-facing SQLite, approved only
├── manifest.json                    # hashes, policy, lineage, reconciliation
├── english_dataset_verified_v1.db.sha256
└── quarantine_v1.db                 # internal only; never bundled with the app
```

During deterministic remediation, the operational artifacts live under
`data/processed/lexical-53k/<validation-run-id>/` and include
`input_manifest.json` and `remediation_report.json`. All of these paths are
already ignored by Git. The legacy database, its manifest, and its existing
sidecars are never changed.

## Non-negotiable contracts

- The import set is exactly all eligible definition rows where the associated
  word’s rank is between 1 and 3,500. There is no pre-import deduplication.
- One source definition gets one `lexical_definition_inputs` row and exactly
  one disposition per remediation run.
- All definition, translation, IPA, and bilingual-example alternatives are
  kept as immutable evidence rows with source-row IDs and snapshot lineage.
- A remediation action may choose or normalize existing evidence; it may not
  synthesize a definition, Vietnamese translation, IPA, or example.
- `approved` stays unavailable to the deterministic runner. It is reserved for
  the later AI reviewer through `ContentRepository.review_candidate`.
- An open quarantine is a work queue, not dropped output. Every retry appends
  an attempt record and either creates a new selection/disposition or leaves
  the previous outcome auditable.
- All long scans use fixed-size reads/writes (250 records per graph write), are
  restart-safe, and have deterministic ordering by rank, word ID, and
  definition ID.

## File map

| File | Responsibility |
| --- | --- |
| `config/settings.py` | Explicit directories for materialized references, remediation artifacts, and versioned releases. |
| `src/learning/schema.py` | Migration 005: immutable input/evidence, rankings, dispositions, attempts, quarantine, canonical mapping, checkpoints, release-build metadata. |
| `src/learning/models.py` | Typed evidence, disposition, remediation, materialization, and release-report contracts. |
| `src/learning/catalog.py` | Idempotent append/query helpers for definition inputs and source snapshot materialization provenance. |
| `src/learning/sqlite_reference_importer.py` | Safe SQLite backup materializer and streaming full-evidence per-definition importer. |
| `src/learning/lexical_evidence.py` | Repository for immutable evidence, ranking decisions, dispositions, checkpoints, attempts, and quarantine cases. |
| `src/learning/lexical_remediation.py` | Deterministic selector, semantic evidence gates, retry-safe remediation runner, and reports. |
| `src/learning/quality.py` | Structural gates plus source-evidence semantic gates; no approval transition. |
| `src/learning/verified_lexical_pack.py` | Compose full approved release and reconciliation record. |
| `src/learning/verified_lexical_exporter.py` | Atomic SQLite/manifest/quarantine exporter with integrity and hash checks. |
| `src/learning/cli.py`, `src/pipeline/cli.py` | Explicit materialize, import, remediate, retry, report, and guarded release commands. |
| `docs/learning-graph-operations.md` | 53k operator workflow, resumability, artifacts, and AI-review TODO. |
| `tests/test_learning/` | Focused migration, materialization/import, evidence, remediation, reporting, release, and CLI coverage. |

## Task 1: Persist the 53k input/evidence/remediation model

**Files:**
- Modify: `src/learning/schema.py`, `src/learning/models.py`,
  `src/learning/store.py`
- Create: `tests/test_learning/test_lexical_evidence_schema.py`
- Modify: `tests/test_learning/test_models.py`, `tests/test_learning/test_schema.py`

- [ ] **Step 1: Write failing migration/model tests.** Cover a fresh v5 graph
  and an upgraded v4 graph. Prove FK relationships, enum/check constraints,
  an input’s unique run disposition, and rollback on invalid evidence role.

- [ ] **Step 2: Add migration 005 without editing historical migrations.**
  Add the new table names to `GRAPH_TABLES` and append `(5, MIGRATION_005)` to
  `MIGRATIONS`. Use the existing snapshot/rebuild migration helper only if a
  changed old table requires it; the new tables must otherwise be additive.
  Create these tables and indexes:

  ```sql
  lexical_definition_inputs(
      input_id PK, snapshot_id FK, raw_record_id UNIQUE FK,
      source_word_id BIGINT, source_definition_id BIGINT,
      input_key UNIQUE, source_definition_sha256, lemma, pos, frequency_rank,
      created_at
  );
  lexical_evidence_items(
      evidence_id PK, input_id FK, evidence_role,
      source_row_id, source_name, value_json, value_sha256, created_at,
      UNIQUE(input_id, evidence_role, source_row_id, value_sha256)
  );
  lexical_evidence_rankings(
      validation_run_id FK, input_id FK, evidence_id FK, evidence_role,
      rank, selected, eligible, reason_json,
      PRIMARY KEY(validation_run_id, input_id, evidence_id)
  );
  lexical_input_canonical_map(
      input_id PK FK, canonical_key, candidate_id FK NULL, mapped_at
  );
  lexical_input_dispositions(
      validation_run_id FK, input_id FK, state, candidate_id FK NULL,
      failure_codes_json, rationale_json, updated_at,
      PRIMARY KEY(validation_run_id, input_id)
  );
  lexical_remediation_attempts(
      attempt_id PK, validation_run_id FK, input_id FK, attempt_number,
      selection_json, outcome, failure_codes_json, rationale_json, created_at,
      UNIQUE(validation_run_id, input_id, attempt_number)
  );
  lexical_quarantine_cases(
      case_id PK, input_id UNIQUE FK, latest_validation_run_id FK,
      status, retry_count, failure_codes_json, alternatives_json, updated_at
  );
  lexical_run_checkpoints(
      validation_run_id FK, phase, last_input_key, processed_count,
      completed_at, updated_at, PRIMARY KEY(validation_run_id, phase)
  );
  lexical_release_builds(
      release_build_id PK, validation_run_id FK, release_version UNIQUE,
      manifest_sha256, counts_json, output_path, created_at
  );
  ```

  `evidence_role` is restricted to `definition`, `translation`, `ipa`, or
  `example`; disposition is restricted to `validated`, `quarantined`, or
  `rejected`; quarantine status is `open`, `resolved`, or `rejected`.
  Index `(snapshot_id, frequency_rank, input_key)`, input/run disposition,
  evidence lookup, and open quarantine work-queue lookup.

- [ ] **Step 3: Define frozen Pydantic/dataclass contracts.** Include typed
  `LexicalDefinitionInput`, `EvidenceItem`, `EvidenceRanking`,
  `InputDisposition`, `RemediationAttempt`, and `RemediationRunReport`.
  Require canonical JSON and 64-hex SHA values at construction; validate
  source IDs and prohibit `approved` as a deterministic disposition.

- [ ] **Step 4: Run focused migrations then all learning tests.**

  ```bash
  ./.venv/bin/pytest tests/test_learning/test_models.py \
    tests/test_learning/test_schema.py \
    tests/test_learning/test_lexical_evidence_schema.py -v
  ./.venv/bin/pytest tests/test_learning/ -v
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add src/learning/schema.py src/learning/models.py src/learning/store.py \
    tests/test_learning/test_models.py tests/test_learning/test_schema.py \
    tests/test_learning/test_lexical_evidence_schema.py
  git commit -m "feat(learning): persist lexical evidence remediation state"
  ```

## Task 2: Materialize an immutable reference and import every definition’s full evidence

**Files:**
- Modify: `config/settings.py`, `src/learning/catalog.py`,
  `src/learning/sqlite_reference_importer.py`
- Modify: `tests/test_learning/test_catalog.py`,
  `tests/test_learning/test_sqlite_reference_importer.py`
- Create: `tests/test_learning/test_sqlite_reference_materializer.py`

- [ ] **Step 1: Add RED tests.** Build a WAL-mode fixture and prove that
  materialization produces a queryable standalone SQLite file, records its
  SHA-256 as the source snapshot, and never modifies the input or its sidecars.
  Test an input word with two definitions and more than three linked bilingual
  sentences: the new importer must create two definition raw records and retain
  every sentence. Test source-path URI characters, mutable-source swap, batch
  boundaries at 250/251, idempotent rerun, and a final count equal to eligible
  definition rows—not eligible words.

- [ ] **Step 2: Add `SQLiteReferenceMaterializer`.** It opens the original
  source read-only and uses SQLite’s backup API to write a new database to
  `data/processed/lexical-53k/snapshots/<materialized-sha>/reference.db` via a
  temporary sibling then atomic rename. The source asset supplied for the
  mutable database continues to verify the source main-file hash. After backup,
  create or return a deterministic *derived* approved source asset named
  `<source-asset-id>.materialized.<sha12>` with the materialized SHA, inherited
  license/attribution/redistribution fields, and an asset version suffixed with
  `+materialized.<sha12>`. Register **that materialized file** with
  `SourceCatalog.record_source_snapshot`; this preserves the catalog’s rule
  that an asset checksum exactly matches its snapshot.

  Capture the originating asset ID, original main/WAL/SHM hashes, materialized
  asset ID, and materialized SHA in an immutable provenance raw record. Do not
  register the mutable source path as the snapshot, and do not treat a
  materialized snapshot as byte-identical to a WAL-backed main database.

- [ ] **Step 3: Add `import_ranked_definitions`.** Keep
  `import_vertical_slice` unchanged for existing bounded-pack compatibility.
  The new method streams the materialized database ordered by
  `(frequency_rank, words.id, definitions.id)`, emits one
  `RawRecordInput(record_type="sqlite_lexical_definition_evidence")` per
  eligible `definitions.id`, and external key
  `sqlite-lexical-definition:{word_id}:{definition_id}`. Each payload contains:

  - word row (source word ID, lemma, POS, rank, stored CEFR, IPA variants and
    source);
  - this definition row, including definition ID, English/Vietnamese values,
    definition-level example, and source;
  - every definition on the word as definition/translation alternatives;
  - every linked bilingual sentence, with sentence ID, link rank, source and
    text; and
  - source table/row IDs needed to reproduce every value.

  The importer must write batches directly only from the checked private
  materialized copy; it must not use `LIMIT 3`, re-open the mutable input, or
  accumulate the 53k payloads in memory. Add catalog helpers that insert the
  matching `lexical_definition_inputs` and `lexical_evidence_items`
  transactionally and idempotently with raw-record append results.

- [ ] **Step 4: Verify the importer.**

  ```bash
  ./.venv/bin/pytest tests/test_learning/test_catalog.py \
    tests/test_learning/test_sqlite_reference_materializer.py \
    tests/test_learning/test_sqlite_reference_importer.py -v
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add config/settings.py src/learning/catalog.py \
    src/learning/sqlite_reference_importer.py tests/test_learning/test_catalog.py \
    tests/test_learning/test_sqlite_reference_materializer.py \
    tests/test_learning/test_sqlite_reference_importer.py
  git commit -m "feat(learning): import complete ranked lexical evidence"
  ```

## Task 3: Build deterministic evidence selection and semantic quality gates

**Files:**
- Create: `src/learning/lexical_evidence.py`,
  `src/learning/lexical_remediation.py`
- Modify: `src/learning/quality.py`, `src/learning/repository.py`,
  `src/learning/lexical_audit.py`
- Create: `tests/test_learning/test_lexical_evidence.py`,
  `tests/test_learning/test_lexical_remediation.py`
- Modify: `tests/test_learning/test_quality.py`,
  `tests/test_learning/test_lexical_audit.py`,
  `tests/test_learning/test_repository.py`

- [ ] **Step 1: Write failing golden tests from the pilot.** The tests must
  demonstrate that the legacy structural gate would pass but the new policy
  quarantines: lexical `do` paired with auxiliary use; `word` verb definition
  paired with noun sentence; concessive `yet` paired with temporal use; and an
  example without the lemma. Also cover valid inflection, a definition-level
  example outranking a weak linked sentence, a missing translation/IPA, exact
  duplicate canonical keys, and conflicting POS/translation evidence.

- [ ] **Step 2: Implement the evidence repository.** It must fetch one input’s
  full evidence, upsert all ranking rows in one transaction, write a single
  disposition, append remediation attempts, manage an open/resolved quarantine
  case, and checkpoint batches. Query order must be explicit and stable. A
  retry of the same input/policy/selection must return the existing result,
  never duplicate an attempt or raw record.

- [ ] **Step 3: Implement `LexicalEvidenceSelector` and new gate codes.**
  Rank existing evidence by verified provenance, lemma or recognized inflection
  occurrence, POS/form compatibility, bilingual translation quality, trusted
  IPA, then source row ID. Persist every candidate’s eligibility/rank/reason,
  including unselected alternatives. Extend `QualityGate` with deterministic
  source-evidence validation rather than statistical or generative guesses:

  - `example.lemma_missing`
  - `example.pos_or_form_mismatch`
  - `example.sense_unproven`
  - `translation.missing_or_invalid`
  - `translation.quality_unknown`
  - `ipa.missing_or_unverified`
  - `provenance.incomplete`
  - `source_evidence_conflict`

  `sense.complete` may remain as a compatibility summary only; it is no longer
  evidence of semantic correctness.

- [ ] **Step 4: Replace the word-bundle audit path with
  `LexicalRemediationService`.** For each imported input, build a candidate
  only from selected evidence, map the input to its deterministic canonical
  key, persist gate results, then write only `validated`, `quarantined`, or
  `rejected`. A passing candidate moves from `candidate` to `validated`;
  failure opens/updates a quarantine case and records alternatives/attempt
  history. Resume from `lexical_run_checkpoints` after a crash. Keep
  `LexicalAuditService` as a thin backwards-compatible adapter for
  `sqlite_lexical_bundle`; do not route 53k work through its old shared,
  three-example behavior.

- [ ] **Step 5: Test for deterministic, non-approval behavior.** Rerun a
  completed run and an interrupted run; assert identical selections,
  disposition counts, candidate count, and no `approved` state. Assert every
  input receives exactly one run disposition, duplicate inputs map to the same
  canonical key while retaining their distinct input rows, and failed cases
  retain their alternatives/retries.

  ```bash
  ./.venv/bin/pytest tests/test_learning/test_quality.py \
    tests/test_learning/test_lexical_evidence.py \
    tests/test_learning/test_lexical_remediation.py \
    tests/test_learning/test_lexical_audit.py \
    tests/test_learning/test_repository.py -v
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add src/learning/lexical_evidence.py src/learning/lexical_remediation.py \
    src/learning/quality.py src/learning/repository.py src/learning/lexical_audit.py \
    tests/test_learning/test_quality.py tests/test_learning/test_lexical_evidence.py \
    tests/test_learning/test_lexical_remediation.py \
    tests/test_learning/test_lexical_audit.py tests/test_learning/test_repository.py
  git commit -m "feat(learning): remediate lexical senses from source evidence"
  ```

## Task 4: Produce reconciliation reports and a durable quarantine export

**Files:**
- Create: `src/learning/lexical_reporting.py`,
  `tests/test_learning/test_lexical_reporting.py`
- Modify: `src/learning/cli.py`, `src/pipeline/cli.py`,
  `tests/test_learning/test_cli.py`

- [ ] **Step 1: Write report tests.** Use a mixed fixture and assert sorted,
  hash-stable JSON contains the exact input total, counts by state, rank band,
  POS, source, gate code, retry outcome and canonical conflict type. Assert
  `input_total == validated + quarantined + rejected` and fail the report if a
  disposition is missing. Verify samples contain evidence IDs/row IDs, not
  untraceable text alone.

- [ ] **Step 2: Implement `LexicalRunReporter`.** Write
  `input_manifest.json` during import and `remediation_report.json` atomically
  under the validation-run directory. Add `QuarantineExporter` to write an
  internal SQLite file with `quarantine_cases`, `remediation_attempts`,
  `evidence_items`, and selected/ranked alternatives. Run `integrity_check`,
  `foreign_key_check`, and emit a SHA-256 file. It must not be suitable for
  app lookup and must contain no approval assertion.

- [ ] **Step 3: Add explicit CLI commands.**

  ```text
  curriculum materialize-lexical-reference --reference-db --asset-id --output-path
  curriculum import-ranked-lexical-reference --reference-db --snapshot-id --import-run-id
  curriculum remediate-lexical --snapshot-id [--validation-run-id] [--resume]
  curriculum retry-lexical-quarantine --validation-run-id --input-id
  curriculum report-lexical-remediation --validation-run-id --output-dir
  ```

  Commands print IDs/paths only, return exit 2 for a blocked contract, and
  never invoke the legacy DAG or mutate the source/reference database.

- [ ] **Step 4: Verify.**

  ```bash
  ./.venv/bin/pytest tests/test_learning/test_lexical_reporting.py \
    tests/test_learning/test_cli.py -v
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add src/learning/lexical_reporting.py src/learning/cli.py src/pipeline/cli.py \
    tests/test_learning/test_lexical_reporting.py tests/test_learning/test_cli.py
  git commit -m "feat(learning): report lexical remediation and quarantine"
  ```

## Task 5: Build the guarded verified-dataset release exporter

**Files:**
- Create: `src/learning/verified_lexical_pack.py`,
  `src/learning/verified_lexical_exporter.py`,
  `tests/test_learning/test_verified_lexical_pack.py`,
  `tests/test_learning/test_verified_lexical_exporter.py`
- Modify: `src/learning/cli.py`, `src/pipeline/cli.py`,
  `config/settings.py`, `tests/test_learning/test_cli.py`

- [ ] **Step 1: Add release-builder RED tests.** Test that an empty graph,
  a merely validated candidate, an open quarantine, a missing disposition, or
  a mismatched reconciliation total all block export. Test a fully resolved
  fixture with two raw inputs mapping to one approved canonical sense and one
  explicitly rejected input: output contains one sense, provenance lists both
  raw IDs, and manifest accounts for all three inputs.

- [ ] **Step 2: Implement `VerifiedLexicalPackComposer`.** Query approved
  revisions sourced from the named validation run, gate-pass evidence, and
  canonical mappings. Enforce the release bar before returning a pack:
  exactly one disposition per input; zero `quarantined`; every production
  candidate/revision is approved; every excluded input is rejected; counts
  reconcile exactly. Unlike the existing CEFR pilot composer, this composer is
  the complete rank-1–3500 release and has no per-source minimum of 30 senses.

- [ ] **Step 3: Implement atomic exporter.** Write a staging directory then
  atomically rename it to the versioned release directory. The SQLite schema is
  exactly:

  ```sql
  senses(sense_id PK, stable_key UNIQUE, lemma, pos, definition_en,
         definition_vi, ipa_uk, ipa_us, frequency_rank, cefr_level);
  sense_examples(sense_id FK, rank, text_en, text_vi, source,
                PRIMARY KEY(sense_id, rank));
  sense_provenance(sense_id FK, snapshot_id, raw_record_id, source_word_id,
                    source_definition_id, evidence_json,
                    PRIMARY KEY(sense_id, raw_record_id));
  release_metadata(key PRIMARY KEY, value);
  ```

  Create lookup indexes for lemma/POS, rank, CEFR, examples, and provenance.
  Write the corresponding `manifest.json` (policy/version/build timestamp,
  source attribution, graph snapshot hashes, and exact count reconciliation),
  checksum, and internal `quarantine_v1.db`. Validate SQLite integrity and
  foreign keys before publication and reject an existing destination.

- [ ] **Step 4: Add `curriculum export-verified-lexical`.** It accepts
  `--validation-run-id --version --output-dir`, has no implicit default output,
  and prints the manifest path on success. Store its manifest hash/counts in
  `lexical_release_builds` only after every file check passes.

- [ ] **Step 5: Verify.**

  ```bash
  ./.venv/bin/pytest tests/test_learning/test_verified_lexical_pack.py \
    tests/test_learning/test_verified_lexical_exporter.py \
    tests/test_learning/test_cli.py -v
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add config/settings.py src/learning/verified_lexical_pack.py \
    src/learning/verified_lexical_exporter.py src/learning/cli.py src/pipeline/cli.py \
    tests/test_learning/test_verified_lexical_pack.py \
    tests/test_learning/test_verified_lexical_exporter.py tests/test_learning/test_cli.py
  git commit -m "feat(learning): export verified lexical dataset releases"
  ```

## Task 6: Document the operator runbook and run final verification

**Files:**
- Modify: `docs/learning-graph-operations.md`,
  `docs/superpowers/specs/2026-08-18-lexical-53k-evidence-remediation-design.md`
- Create: `tests/test_learning/test_lexical_53k_contract.py`

- [ ] **Step 1: Add a contract integration test.** With a small SQLite fixture,
  execute materialize → import → remediate → report; assert the source SHA and
  mtime are unchanged, all definitions are accounted for, no approval was
  created, and the report/quarantine outputs have verified hashes. Use a fake
  fully reviewed fixture only for the release-builder acceptance test.

- [ ] **Step 2: Document the exact commands.** Include preflight disk space for
  the private SQLite copy, resume semantics, artifact paths, how to inspect an
  open quarantine, and the explicit AI-review TODO. Replace the design-status
  line with `Approved for implementation` and link this plan. State plainly
  that `english_dataset_verified_v1.db` cannot be emitted until the deferred
  reviewer has resolved each validation/quarantine outcome.

- [ ] **Step 3: Run quality gates and the full suite.**

  ```bash
  ./.venv/bin/pytest tests/test_learning/ -v
  make test
  ./.venv/bin/black --check <all changed Python files>
  ./.venv/bin/ruff check <all changed Python files>
  git diff --check
  ```

  If a repository-wide formatter check reports unrelated pre-existing files,
  report that fact and keep Black/Ruff validation scoped to changed files.

- [ ] **Step 4: Commit.**

  ```bash
  git add docs/learning-graph-operations.md \
    docs/superpowers/specs/2026-08-18-lexical-53k-evidence-remediation-design.md \
    tests/test_learning/test_lexical_53k_contract.py
  git commit -m "docs(learning): document 53k lexical remediation workflow"
  ```

## Execution checklist for the real 53,270 run

This is an operational run after Task 6, not a test fixture and not a Git
commit. Record the commands, source/materialized hashes, validation-run ID,
input total and final report path in the run log.

1. Hash `data/output/english_dataset.db` and its WAL/SHM files; verify it is
   the intended reference and has sufficient free disk for a private backup.
2. Materialize it under `data/processed/lexical-53k/snapshots/`, register the
   materialized output as the approved source snapshot, and re-hash the legacy
   database to prove it was untouched.
3. Run `import-ranked-lexical-reference`; require exactly 53,270 imported or
   existing definition inputs before continuing.
4. Run `remediate-lexical` and `report-lexical-remediation`; reconcile all
   state counts exactly to 53,270. Inspect deterministic failure distribution
   and evidence samples—not only summary percentages.
5. Export `quarantine_v1.db` and retain it with its report/hash. Do not
   manually delete or hide bad records.
6. Stop at pre-release while any case is quarantined or candidate is only
   validated. The future AI-review task processes `validated` candidates and
   quarantine cases, records auditable approvals/rejections, then the guarded
   `export-verified-lexical` command may create the new application database.

## Deferred follow-up

The next plan after this one is **AI lexical adjudication**, not another small
core pack. It will consume `validated` candidates and `lexical_quarantine_cases`
in bounded batches, preserve prompts/model/version/evidence/verdicts, call
`ContentRepository.review_candidate` for the final approved/rejected decision,
and unlock the guarded release exporter. It must not bypass, overwrite, or
weaken the evidence/remediation contracts above.

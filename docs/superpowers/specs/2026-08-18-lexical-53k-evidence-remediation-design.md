# Lexical 53k evidence-remediation pipeline

**Status:** Ready for user review before implementation planning  
**Date:** 2026-08-18

## Purpose

Build an auditable, self-owned remediation pipeline for every one of the
**53,270 definitions whose word frequency rank is 1–3,500** in
`english_dataset.db`. The pipeline must turn raw lexical data into a clean,
versioned backend dataset without overwriting raw sources or silently accepting
incomplete records.

The user-facing product is an offline English-learning backend: vocabulary,
definitions, Vietnamese translations, IPA, and bilingual examples. The system
must not require third-party runtime APIs to serve this content.

## Pilot evidence and design constraint

The first 30-sense pilot showed that structural validation alone is
insufficient: all 30 records passed the existing `sense.complete` gate, while
human semantic review quarantined 11 because the selected definition and
example represented different senses, POS uses, or no lexical evidence at all.

The design therefore treats a non-empty field as insufficient evidence. A
candidate must retain and justify the particular evidence selected for its
definition, Vietnamese translation, IPA, and example.

## Scope

### In scope

- All 53,270 input definitions in the frequency-rank range 1–3,500.
- Immutable source snapshots and raw evidence preservation.
- Evidence inventory, candidate construction, deterministic validation,
  deterministic remediation, quarantine/retry handling, and release reporting.
- A clean, versioned SQLite release artifact for application backends.
- Full lineage from every output or terminal decision back to source snapshot
  and source row identifiers.

### Explicitly deferred

- AI adjudication/review implementation. It is a later stage, but this design
  stores the evidence, failure codes, and retry history needed by that stage.
- Expanding beyond the 53,270 ranked definitions.
- Replacing or mutating `data/output/english_dataset.db`.

## Definitions and invariants

- **Raw definition:** one source definition row in the 53,270 input set.
- **Evidence item:** a source-backed definition, translation, IPA, or bilingual
  example linked to a raw definition/word and source snapshot.
- **Canonical sense candidate:** a proposed backend sense built from selected
  evidence; it is not itself an assertion that the raw source is clean.
- **Disposition:** the terminal or interim status assigned to every raw
  definition for a validation run.

For each validation run:

1. Every raw definition has exactly one explainable disposition.
2. Raw source values are immutable and never overwritten by remediation.
3. A canonical candidate preserves links to all selected and rejected evidence.
4. No record becomes `approved` merely because required fields are non-empty.
5. Processing is idempotent, resumable, and policy-versioned.

## State model

```text
raw immutable record
  -> evidence bundle
  -> canonical sense candidate
  -> validated | quarantined | rejected
  -> AI-reviewed approved                 (deferred implementation)
  -> production release
```

- `validated` means deterministic rules found no blocking condition; it is
  eligible for later AI adjudication, not production publication by itself.
- `quarantined` means recoverable evidence is missing, ambiguous, conflicting,
  or unsuitable. It remains in a remediation queue.
- `rejected` means the source record is noise, malformed, or cannot be made
  usable with source-backed evidence. It remains auditable but never appears in
  a release.
- `approved` is reserved for the later AI adjudication verdict.

## Data flow

```text
53,270 raw definitions
  -> immutable evidence inventory
  -> canonicalize and map duplicates
  -> choose best source-backed evidence
  -> deterministic validation and repair
  -> validated / quarantined / rejected
  -> AI adjudication (later)
  -> approved production release
```

Input cardinality is not reduced before processing: all 53,270 records receive
a disposition. Canonical deduplication is allowed only in the output model and
must maintain an explicit input-to-canonical mapping.

## Pipeline stages

### 1. Freeze the source and enumerate the input contract

Register a source asset and verified snapshot for the source database. Build an
immutable input manifest containing every eligible definition and its original
word, definition, sentence-link, source, and snapshot identifiers.

The source database may not be mutated. SQLite volatile sidecars must be
rejected or safely materialized into an immutable, hash-verified snapshot before
import.

### 2. Build complete evidence bundles

For each input definition, collect rather than truncate:

- source definition and all available alternative definitions;
- existing Vietnamese translations and their sources;
- IPA variants and provenance;
- all linked bilingual examples, not just the first few;
- word lemma, POS, rank, CEFR mapping, source identifiers, and raw row IDs.

Evidence is stored with source and snapshot lineage. This enables later retry
without re-crawling or losing the prior choice.

### 3. Canonicalize without losing source distinctions

Create a deterministic candidate key from normalized lemma, POS, definition
identity, and source-backed evidence. Exact duplicates may share one canonical
candidate, but each input definition continues to have its own evidence and
disposition record.

Conflicting definitions, translations, POS tags, or source claims are not
collapsed silently; they produce an evidence-conflict failure for remediation.

### 4. Rank and select evidence

Select the strongest available evidence deterministically. Ranking must prefer:

1. verified source provenance;
2. an example containing the lemma or a validated inflection;
3. a POS/form compatible use;
4. a clean, non-passthrough bilingual pair;
5. an IPA value with a trusted source and adequate confidence;
6. stable, deterministic tie-breaking by source quality and row ID.

Selections and rejected alternatives are persisted so the decision can be
reproduced and challenged later.

### 5. Validate and repair deterministically

The remediation phase may select better existing source evidence and normalize
safe formatting. It must not invent definitions, translations, or examples.

Typical failures include:

- `example.lemma_missing`
- `example.pos_or_form_mismatch`
- `example.sense_unproven`
- `translation.missing_or_invalid`
- `translation.quality_unknown`
- `ipa.missing_or_unverified`
- `provenance.incomplete`
- `source_evidence_conflict`

Each repair attempt records the policy version, attempted evidence IDs, result,
and reason. If no deterministic replacement succeeds, the record enters the
quarantine queue rather than being auto-approved.

### 6. Quarantine lifecycle

Quarantine is a durable remediation work queue, not a discard bucket. A case
contains the current failure codes, ranked evidence alternatives, retry count,
attempt history, and source lineage. It can return to validation after a new
source-backed selection is made.

Later AI adjudication consumes this queue and `validated` candidates. Its output
will decide `approved` versus `rejected`; AI implementation is intentionally
outside this first implementation plan.

## Internal data products

The learning graph remains the internal system of record. It must retain:

- source assets and source snapshots;
- raw records and source row identifiers;
- evidence bundles and selection decisions;
- canonical candidates and input-to-canonical mappings;
- validation runs, policy versions, gate results, dispositions, and repair
  attempts;
- quarantine cases and their complete history.

Batch work must be bounded, resumable, and idempotent. A failed run must not
leave partially classified input records without a recoverable checkpoint.

## Release artifacts

The source database stays unchanged. A successful release is a new versioned
artifact set:

| Artifact | Purpose |
|---|---|
| `english_dataset_verified_v1.db` | Backend-facing SQLite; only AI-approved senses. |
| `manifest.json` | Version, hashes, counts, policy, lineage and source attribution. |
| `quarantine_v1.db` | Internal remediation queue; never shipped to the app. |
| `learning_graph.duckdb` | Internal provenance and audit system used to reproduce releases. |

The release SQLite must expose at least:

- `senses` — stable sense ID/key, lemma, POS, definition EN/VI, IPA, rank and
  CEFR;
- `sense_examples` — ordered bilingual examples and source;
- `sense_provenance` — links to source snapshot and raw definition IDs;
- `release_metadata` — version, policy, hashes and build information.

The release count may be lower than 53,270 because canonicalization and
rejections are allowed. The manifest must nevertheless account for every input
definition and its disposition.

## Completion and release bar

The dataset is only described as clean when:

1. all 53,270 input definitions have a complete evidence bundle and a recorded
   disposition;
2. no record remains in `quarantined` status;
3. every production record is AI-reviewed `approved`;
4. every excluded record is explicitly `rejected` with auditable rationale;
5. the release manifest reconciles input, canonical, approved, rejected, and
   output counts exactly;
6. SQLite integrity, hashes, provenance and all relevant tests pass.

`rejected` is an acceptable final quality decision. An unexplained or
quarantined record is not.

## Verification strategy

### Unit and integration tests

- One focused test for every failure code and remediation branch.
- Golden regression cases from the pilot, including `do` as auxiliary versus
  lexical verb, `word` noun versus verb, and temporal versus concessive `yet`.
- Tests that raw evidence is immutable, selection is deterministic, retries are
  idempotent, and output preserves lineage.
- Tests proving a candidate cannot reach `approved` without the later reviewer
  stage.

### Full-run audit report

Every full run produces a hash-addressed report with counts by source, rank
band, POS, gate code, disposition, retry result, duplicate/conflict type, and
sampled evidence. The report is a release prerequisite, not optional telemetry.

## Out-of-scope decision recorded for later

AI review will be added after the evidence/remediation foundation exists. It
must consume stored evidence and produce auditable verdicts; it must not be a
black-box overwrite of raw data or a reason to bypass the release bar.

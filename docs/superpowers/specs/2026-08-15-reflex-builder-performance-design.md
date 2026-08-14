# Reflex Builder Performance Design

**Date:** 2026-08-15
**Status:** Approved design

## Goal

Make `enrich_reflex` complete predictably instead of spending hours CPU-bound
without visible progress.  Each run creates at most 50,000 speed drills and
50,000 cloze drills while preserving useful, valid distractors.

## Current problem

`ReflexBuilder.build` reconstructs and filters the full Vietnamese-sentence
pool and word pool for every source sentence.  This creates near-quadratic
work and excessive temporary allocations.  Its existing `max_drills_per_type`
argument is not enforced, and writes occur only after a 10,000-record batch,
so a long CPU-bound interval can have neither database movement nor log output.

## Design

### Bounded, deterministic selection

- Keep the public `build(db_mgr, max_drills_per_type=50_000)` interface and
  make the cap effective independently for speed and cloze drills.
- Traverse eligible sentences in a stable, CEFR-balanced order when data is
  available.  Stop producing a drill type as soon as its cap is reached; keep
  processing only if the other type still needs records.
- Use a locally scoped, configurable seeded random generator.  The same input
  and seed produce the same choices without altering global random state.

### Precomputed sampling pools

- Normalise and de-duplicate Vietnamese texts once, then retain compact pools
  suitable for selecting alternatives without rebuilding a full filtered list
  per sentence.
- Load eligible words once and index them by length.  Cloze distractors select
  from the nearby length buckets, falling back safely to the broader pool only
  when necessary.
- Generate exactly three distinct distractors that exclude the correct answer.
  If the dataset cannot provide three valid alternatives, skip that drill and
  count/log the reason rather than emitting invalid data.

### Incremental persistence and observability

- Generate and insert records in a bounded batch size.  Each successful flush
  logs the drill type, source sentences examined, drills created, cap, rate,
  and elapsed time; a final summary records skipped records by reason.
- Raise write failures with the current batch and drill type in the error
  message.  Database changes remain batch-atomic under the staging database's
  existing lock discipline.
- Keep the enrichment step idempotent: before regeneration, clear only
  `reflex_drills` records produced by this step (the table is owned by this
  builder).  A rerun therefore replaces rather than duplicates its output.

## Non-goals

- No schema migration or change to the exported reflex-drill format.
- No attempt to run the current enrich steps concurrently over a shared DuckDB
  connection; that is a separate connection-safety change.
- No change to phrase extraction, translation, or scenario generation.

## Acceptance criteria

1. `enrich_reflex` never creates more than 50,000 speed drills or 50,000 cloze
   drills by default.
2. Its candidate preparation is done once per run; per-sentence generation
   does not scan the whole sentence or word corpus.
3. Progress is logged at every successful batch flush and at completion.
4. Running the builder twice leaves one regenerated set, not duplicates.
5. Tests cover cap enforcement, deterministic seeded output, valid
   distractors, idempotent reruns, and progress/batch behavior.

## Verification

Run focused reflex/scenario tests first, then format and lint changed files,
then run `make test`.  Finally run `make run-tui` against the existing staging
data and confirm that `enrich_reflex` emits periodic progress and finishes
within the intended cap.

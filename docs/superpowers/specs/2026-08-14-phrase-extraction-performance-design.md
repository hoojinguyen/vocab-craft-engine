# Phrase Extraction Performance Design

## Context

The pipeline run started on 2026-08-14 remained in `transform_phrases` for
hours while consuming one CPU core. The existing extractor loads every
sentence and every multi-word lemma into Python, then tests every phrase
regular expression against every sentence. This has quadratic work with
respect to the sentence and phrase candidate sets, offers no intermediate
progress or checkpoint, and retains all discovered links in memory until the
scan completes.

## Goals

- Preserve the `phrases` and `phrase_sentences` output schema and canonical
  phrase semantics.
- Match curated MWE variants to their canonical phrase, including inflections
  such as `gave up` to `give up`.
- Support eligible multi-word lemmas from `words` without an all-pairs regex
  scan.
- Process sentences in resumable batches, with useful progress logging and
  bounded memory use.
- Keep insertions idempotent and retain referential integrity.

## Non-goals

- Changing the curated MWE catalogue, downstream export schema, or the
  pipeline DAG.
- Adding phrase matching for expressions longer than six tokens.
- Retrofitting checkpoints into unrelated pipeline steps.

## Architecture

### Candidate catalogue

Build a temporary, normalized candidate relation at the beginning of
`transform_phrases`.

- Each curated canonical phrase contributes one candidate for its canonical
  form and one for each declared variant.
- Each eligible multi-word lemma from `words` contributes its normalized form
  as both candidate and canonical phrase.
- Eligible forms contain two through six tokens after normalization.
- A candidate row maps its surface form to exactly one canonical phrase and
  carries the type, definition, and CEFR metadata needed to populate
  `phrases`.

Normalization is deterministic: Unicode text is case-folded, punctuation is
treated as a token boundary, and consecutive whitespace is collapsed. This
permits matching across ordinary punctuation and capitalization while keeping
word boundaries explicit.

### Batch n-gram matching

The extractor reads `sentences` in ascending ID batches. For each batch, it
normalizes `text_en`, creates contiguous token n-grams of lengths two through
six, and joins them by equality with the candidate relation. The join produces
`(canonical_phrase, sentence_id)` pairs.

Canonical phrases discovered in a batch are inserted into `phrases` first.
The corresponding phrase IDs are then joined to the matched sentence IDs and
bulk inserted into `phrase_sentences`. Existing unique keys make repeated
batch execution safe.

The implementation must not use the previous nested Python loop or retain all
sentences or all links in Python. DuckDB executes joins and bulk inserts; any
Python work is limited to assembling the finite candidate catalogue and
orchestrating batches.

## Progress and recovery

After each successfully committed batch, save a checkpoint for
`transform_phrases` containing the final sentence ID, cumulative sentence
count, phrase count, and link count. Log the completed sentence count, total
sentence count, matches, throughput, elapsed time, and ETA at the same
boundary. The TUI receives the same progress updates through the existing
progress reporter.

On normal resume, continue after the saved sentence ID. If the source hash or
candidate-catalogue signature differs from the checkpoint metadata, clear only
the phrase-extraction checkpoint and rebuild the step from the beginning. A
batch is checkpointed only after its phrase and link inserts succeed.

An interrupt before that boundary may cause the current batch to be repeated;
the unique constraints on `phrases.phrase` and
`phrase_sentences(phrase_id, sentence_id)` prevent duplicates.

## Error handling

- Empty sentence data returns zero and emits a warning, as today.
- Empty candidate data returns zero and emits a clear informational log.
- A failed batch raises the original error without advancing its checkpoint.
- Temporary candidate relations are scoped to the active DuckDB connection
  and cleaned up on success or error.

## Testing and acceptance criteria

Add focused tests for:

1. Canonical and inflected curated matching.
2. Case and punctuation normalization, plus prevention of substring-only
   matches.
3. Multi-word lemma matching with lengths from two through six tokens.
4. Idempotent execution and foreign-key-valid links.
5. Interrupted execution followed by resume from a saved checkpoint.
6. Batch progress reporting using a deterministic fixture that spans multiple
   batches.

The existing phrase-extractor tests must remain green. Acceptance requires
that the extractor contains no sentence-by-candidate nested regex scan, logs
measurable batch progress, resumes safely, and handles the current staging
data with bounded memory.

## Operational guidance

The currently running `make run-tui` process should be stopped with `Ctrl-C`
before deploying this implementation. Completed upstream steps are already in
the staging database; after the optimized code is installed, `make resume`
should re-run the incomplete `transform_phrases` step and continue the DAG.

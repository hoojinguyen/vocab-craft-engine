# Lossless Scalable Lexical Evidence Design

## Decision

The rank-1–3500 source snapshot contains 57,051 definitions, 14,519,514
word-to-sentence links, and 90,676,891 definition-to-sentence expansions.
The existing importer serializes the same sentence text into every definition
payload and then stores it again in `lexical_evidence_items`. That is not a
safe representation for the available 47 GiB working space.

The graph will preserve every source alternative without retaining repeated
sentence text. A sentence value is immutable source evidence identified by its
snapshot, source table/row and hash. A word-to-sentence link records the
source word, deterministic rank, and source evidence identity once. Definition
inputs retain their source word ID, so an input's complete linked-example set
is obtained by joining the immutable word links. Definition, translation, IPA,
and definition-level example evidence remain input-local because their
cardinality is small and their identity is definition-specific.

## Boundaries

- `english_dataset.db` remains read-only; imports use only the materialized
  private reference.
- No sentence, link, or definition alternative is dropped. The normalized
  tables retain every linked source sentence exactly once and every link once.
- The remediation selector sees the same complete evidence set through a
  repository join. It persists selected evidence, disposition, rationale, and
  the deterministic policy fingerprint. Full alternatives remain queryable
  from normalized evidence rather than being duplicated into ranking rows.
- `lexical_evidence_rankings` records local input evidence; the separate
  `lexical_source_evidence_rankings` records only selected virtual source
  evidence. Neither becomes a 90-million-row duplicate of immutable link
  facts.
- The source contract is manifest-driven: the imported count is recorded in
  the immutable input manifest. For the current materialized snapshot the
  observed all-rank count is 57,051; no pre-import filtering is introduced.
- AI approval and `verified_v1` release remain out of scope.

## Data model

`lexical_source_evidence`
: One source value per `(snapshot_id, evidence_role, source_table,
  source_row_id, value_sha256)`. It stores text, source name, and hash.

`lexical_word_evidence_links`
: One relation per `(snapshot_id, source_word_id, source_evidence_id)` with
  the legacy link rank. This is the complete durable inventory for linked
  bilingual examples.

`lexical_definition_inputs` and `lexical_evidence_items`
: Continue to represent one definition input and its low-cardinality,
  definition-specific alternatives. The raw payload references the normalized
  example scope by word ID instead of embedding all sentence text.

## Runtime flow

1. Stream materialized `word_sentences` in fixed 250-row batches and write
   source evidence plus word links idempotently.
2. Stream source definitions in stable rank/word/definition order and create
   one compact raw record/input per definition.
3. For each remediation input, join local evidence with its word's normalized
   example links; rank deterministically; persist selected source evidence and
   the outcome. The immutable source/link tables provide the complete
   alternatives inventory for any audit or later AI review.
4. The input manifest stores `source_definition_count`,
   `source_linked_example_count`, and normalized evidence/link counts.

## Verification

- Migration tests cover fresh and v6-upgrade schemas, FK/unique constraints,
  and idempotent source/link insertion.
- Import tests prove two definitions sharing five sentences produce five
  source values and five word links, not ten copied text values; reruns remain
  idempotent.
- Evidence repository tests prove both definitions receive all five linked
  examples via joins and that selected virtual evidence has durable lineage.
- A 251-row test proves source-link and definition writes remain bounded.
- The full learning suite and source-main checksum/mtime checks are required
  before the operational import resumes.

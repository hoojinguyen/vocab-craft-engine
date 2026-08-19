# Lexical 53K Remediation Run Design

## Goal

Evaluate all 57,051 lexical definitions with deterministic quality gates and
persist an auditable validation snapshot, while preserving the imported graph
and the original SQLite source as immutable inputs. AI review and human review
remain deferred TODO work; this phase produces reliable machine dispositions
and a durable queue for later review.

## Scope

This phase covers:

- a stratified pilot of 1,000 definitions;
- validation-run, checkpoint, evidence-ranking, disposition, and remediation
  attempt persistence;
- pilot idempotence and resume verification;
- a full run over all 57,051 definitions in resumable batches of 1,000–5,000;
- aggregate quality and operational reporting.

It does not publish a verified release SQLite file and does not invoke an AI or
human reviewer.

## Immutable inputs and isolation

`data/output/english_dataset.db` and the imported lexical graph are read-only
inputs for remediation. All run state is written to the learning graph under a
new `validation_run_id`; reruns use a distinct run ID unless explicitly
resuming the same run. A failed run must not mutate source snapshots,
candidate payloads, or previously completed runs.

## Pilot sampling

The pilot contains exactly 1,000 definitions selected deterministically from
the rank-1–3500 population. Sampling is stratified by rank bands (1–500,
501–1500, 1501–2500, 2501–3500), definition source (Kaikki/WordNet), and
available part-of-speech. A stable hash-based ordering and a recorded sampling
manifest make the same pilot reproducible.

## Validation flow

For each input, the runner streams bounded source evidence, ranks/selects
evidence, executes the existing deterministic gates, and persists:

1. the validation attempt and checkpoint;
2. gate results and failure codes;
3. selected evidence and compact provenance/fingerprints;
4. exactly one run-scoped disposition: `validated` or `quarantined`.

Quarantined inputs retain a machine-readable reason and remain available for a
future AI/human remediation queue. No quarantine is silently discarded.

## Checkpoint and idempotence contract

Each batch commits transactionally and advances a checkpoint only after all
records in that batch are durable. Restarting from a checkpoint must not create
duplicate inputs, evidence, attempts, gate rows, or dispositions. Re-running a
completed pilot with the same run ID must produce the same counts, payload
hashes, fingerprints, and dispositions.

## Promotion criteria

The full run starts only after the pilot demonstrates:

- zero source or foreign-key integrity errors;
- deterministic rerun with no duplicate graph rows;
- successful interruption/resume from a checkpoint;
- bounded memory and acceptable throughput measured per batch;
- every quarantined record has at least one stable failure code and evidence
  fingerprint.

## Full-run reporting

The full run reports total inputs, validated/quarantined counts and rates,
counts by rank band/source/POS, gate failure frequencies, evidence coverage,
retry outcomes (excluding initial attempts), throughput, peak resource usage,
and checkpoint/resume history. The report references the immutable source
snapshot and validation run ID.

## Failure handling

Transient database or process failures stop the current batch without advancing
its checkpoint. Invalid source provenance, malformed payloads, or conflicting
identities fail closed and are recorded as run errors rather than being
converted into successful records. A run may be resumed only from its last
committed checkpoint.

## Output

The primary output is a validation snapshot in the learning graph: run metadata,
gate results, evidence rankings, dispositions, quarantine cases, attempts, and
checkpoints. A human-readable report and sampling manifest are secondary
artifacts. A publishable SQLite dataset is a later phase gated by a separate
release process.


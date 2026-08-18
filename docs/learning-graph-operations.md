# Learning Graph Operations

## Safety boundary

The canonical learning graph uses `data/processed/learning_graph.duckdb`; it is separate from legacy staging and from published curriculum packs. Curriculum commands do not migrate, reset, or modify `data/processed/staging.duckdb` or `data/output/english_dataset.db`. A published pack is an independent SQLite/JSON directory and is never overwritten.

## Source approval input

Register one reviewed YAML mapping with every `SourceAssetInput` field: `asset_id`, `title`, `locator`, `asset_version`, `sha256`, `license_id`, `license_url`, `attribution`, `redistribution_allowed`, and `validation_status`.

`approved` requires a non-empty licence identifier and attribution plus `redistribution_allowed: true`. Use `quarantined` for an asset whose rights or validation evidence is inadequate. Unknown or incomplete licensing blocks approval and therefore blocks publication.

## Review lifecycle

Content moves from `candidate` to `validated`, then to `approved`, `rejected`, or
`quarantined`. Deterministic lexical remediation may produce only `validated` or
`quarantined`; it never approves content. The deferred AI reviewer is the only
operational path that may call the final `approved`/`rejected` decision. An
approval creates an immutable canonical revision; payloads are never edited in
place. To correct approved content, create a new approved revision (N+1) from
its prior revision. Every review keeps its reviewer, decision, rationale,
candidate, and revision link.

## General commands

Initialize the dedicated graph database:

```bash
python main.py curriculum init --db-path data/processed/learning_graph.duckdb
```

Register a reviewed source manifest:

```bash
python main.py curriculum register-source --manifest path/to/source.yaml
```

Snapshot legacy `words` records into append-only raw references:

```bash
python main.py curriculum snapshot-reference --reference-db data/processed/staging.duckdb --source-id approved-source-id --import-run-id 2026-08-17
```

The controlled lexical workflow keeps the legacy SQLite reference immutable:

```bash
python main.py curriculum register-source --manifest data/manifests/legacy-sqlite.yaml
SOURCE_SNAPSHOT_ID="$(python main.py curriculum snapshot-source \
  --asset-id legacy-sqlite \
  --local-path data/output/english_dataset.db \
  --retrieved-at 2026-08-17T00:00:00+00:00)"
python main.py curriculum snapshot-lexical-reference \
  --reference-db data/output/english_dataset.db \
  --snapshot-id "$SOURCE_SNAPSHOT_ID" \
  --import-run-id 2026-08-17-lexical-v1
VALIDATION_RUN_ID="$(python main.py curriculum audit-lexical \
  --snapshot-id "$SOURCE_SNAPSHOT_ID")"
python main.py curriculum report-lexical \
  --validation-run-id "$VALIDATION_RUN_ID" \
  --output-path data/output/reports/lexical-v1.json
python main.py curriculum review-candidate \
  --candidate-id CANDIDATE_ID \
  --decision approved \
  --reviewer-id editor-1 \
  --rationale "Reviewed against the lexical checklist"
python main.py curriculum compose-lexical \
  --validation-run-id "$VALIDATION_RUN_ID" \
  --pack-id lexical-a1 \
  --version 0.1.0 \
  --cefr-level A1 \
  --output-dir data/output/lexical/lexical-a1-0.1.0
```

Only candidates in `validated` state can be approved. The audit quarantines
failed senses with stable gate codes; composition includes only approved senses
that passed the named validation run and have at least 30 approved senses per
source asset in the selected CEFR band.

Compose and publish one approved module revision selected by stable key:

```bash
python main.py curriculum compose --module module.a0.greetings --pack-id a0-a1-pilot --version 0.1.0 --output-dir data/output/curriculum/a0-a1-pilot
```

Blocked commands return exit status `2` and write a concise explanation to standard error.

## 53k lexical evidence-remediation workflow

This is the workflow for the complete rank-1–3500 lexical input set. It is
separate from the bounded `snapshot-lexical-reference`, `audit-lexical`, and
`compose-lexical` pilot commands above.

### Preflight

- Treat `data/output/english_dataset.db` and any `-wal`/`-shm` sidecars as
  read-only input. Never run a cleanup or export command against that path.
- Ensure the source asset is registered from a reviewed manifest whose SHA-256
  is the source main database checksum and whose redistribution rights are
  approved.
- Reserve disk space for at least one private materialized SQLite copy plus
  remediation graph, report, and quarantine artifacts. Keep substantial free
  headroom beyond the source database size.
- Use one dedicated `data/processed/learning_graph.duckdb`; direct catalog or
  graph writes are an internal trusted pipeline boundary, not an operator API.

Materialize first. This prints the **materialized snapshot ID** followed by the
immutable private SQLite path; record both values in the run log:

```bash
python main.py curriculum materialize-lexical-reference \
  --db-path data/processed/learning_graph.duckdb \
  --reference-db data/output/english_dataset.db \
  --asset-id legacy-sqlite \
  --output-path data/processed/lexical-53k/snapshots
```

Import only that printed materialized path. The importer enumerates one input
per eligible source definition, preserving all evidence alternatives. It writes
the ordered `input_manifest.json` below `data/processed/lexical-53k/`:

```bash
python main.py curriculum import-ranked-lexical-reference \
  --db-path data/processed/learning_graph.duckdb \
  --reference-db MATERIALIZED_REFERENCE_DB \
  --snapshot-id MATERIALIZED_SNAPSHOT_ID \
  --import-run-id 2026-08-18-lexical-53k
```

Before remediation, require the manifest's `input_total` to be exactly
`53,270` for the intended source. Do not continue on a lower count, a higher
count, or an unexplained mismatch.

Run deterministic remediation and retain its printed validation-run ID:

```bash
python main.py curriculum remediate-lexical \
  --db-path data/processed/learning_graph.duckdb \
  --snapshot-id MATERIALIZED_SNAPSHOT_ID
```

If a process stops after a checkpoint, resume the same immutable run rather
than beginning another one:

```bash
python main.py curriculum remediate-lexical \
  --db-path data/processed/learning_graph.duckdb \
  --snapshot-id MATERIALIZED_SNAPSHOT_ID \
  --validation-run-id VALIDATION_RUN_ID \
  --resume
```

Write and inspect the reconciled report and durable internal quarantine queue:

```bash
python main.py curriculum report-lexical-remediation \
  --db-path data/processed/learning_graph.duckdb \
  --validation-run-id VALIDATION_RUN_ID \
  --output-dir data/processed/lexical-53k/VALIDATION_RUN_ID

sqlite3 data/processed/lexical-53k/VALIDATION_RUN_ID/quarantine_v1.db \
  'SELECT status, count(*) FROM quarantine_cases GROUP BY status;'
```

`remediation_report.json` must reconcile `validated + quarantined + rejected`
to the same input total. Keep `quarantine_v1.db` and its SHA-256 file; a
quarantine is a durable work queue, never a record to delete or hide.

### Deferred AI-review TODO and guarded release

The next operational stage is AI adjudication in bounded, auditable batches. It
must preserve prompt, model/version, selected evidence, verdict, and rationale;
then call `ContentRepository.review_candidate` for the final `approved` or
`rejected` transition. It must not overwrite raw evidence, bypass the graph, or
approve a quarantined input without an auditable decision.

Until that stage resolves every input, `english_dataset_verified_v1.db` must
not be emitted. Once all inputs are explicit `approved` production candidates
or `rejected` exclusions, with zero open quarantines, the guarded command is:

```bash
python main.py curriculum export-verified-lexical \
  --db-path data/processed/learning_graph.duckdb \
  --validation-run-id VALIDATION_RUN_ID \
  --version verified-v1 \
  --output-dir data/output/lexical-releases/english_dataset_verified_v1
```

It creates a new directory atomically and refuses to overwrite an existing
release. The resulting `english_dataset_verified_v1.db` is the backend-facing
artifact; `quarantine_v1.db` is internal only. The release manifest, checksums,
source attribution, source snapshot hashes, and `lexical_release_builds` ledger
are release prerequisites.

## Release checklist

- All quality gates pass.
- SQLite `integrity_check` and `foreign_key_check` pass.
- Manifest and checksum files match the exported SQLite and JSON files.
- The 53k input manifest total is exactly 53,270 and the remediation report
  reconciles every input.
- The original source SHA-256 and mtime are unchanged after materialization,
  import, remediation, and reporting.
- There are zero open quarantines and every production sense is AI-approved;
  every excluded input is explicitly rejected.
- Verify `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, release
  checksums, source snapshot hashes, and the `lexical_release_builds` record
  before publishing.

## Rollback

Never overwrite a published pack. Withdraw an unsuitable pack operationally, preserve its manifest for audit, correct the graph through a new revision, and compose a new version into a new output directory.

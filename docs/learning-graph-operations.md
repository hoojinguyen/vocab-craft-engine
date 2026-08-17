# Learning Graph Operations

## Safety boundary

The canonical learning graph uses `data/processed/learning_graph.duckdb`; it is separate from legacy staging and from published curriculum packs. Curriculum commands do not migrate, reset, or modify `data/processed/staging.duckdb` or `data/output/english_dataset.db`. A published pack is an independent SQLite/JSON directory and is never overwritten.

## Source approval input

Register one reviewed YAML mapping with every `SourceAssetInput` field: `asset_id`, `title`, `locator`, `asset_version`, `sha256`, `license_id`, `license_url`, `attribution`, `redistribution_allowed`, and `validation_status`.

`approved` requires a non-empty licence identifier and attribution plus `redistribution_allowed: true`. Use `quarantined` for an asset whose rights or validation evidence is inadequate. Unknown or incomplete licensing blocks approval and therefore blocks publication.

## Review lifecycle

Content moves from `candidate` to `approved`, `rejected`, or `quarantined`. An approval creates an immutable canonical revision; payloads are never edited in place. To correct approved content, create a new approved revision (N+1) from its prior revision. Every review keeps its reviewer, decision, rationale, candidate, and revision link.

## Commands

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

## Release checklist

- All quality gates pass.
- SQLite `integrity_check` and `foreign_key_check` pass.
- Manifest and checksum files match the exported SQLite and JSON files.
- A human samples the module's English, Vietnamese, dialogue, scenario, and assessed activity content.
- For a lexical pack, inspect the gate-code report, approve the required sample,
  and verify `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and the
  manifest's `lexical.db`/`lexical.json` hashes before publishing.

## Rollback

Never overwrite a published pack. Withdraw an unsuitable pack operationally, preserve its manifest for audit, correct the graph through a new revision, and compose a new version into a new output directory.

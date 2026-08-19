# Lexical 53K Remediation Runbook

## Pilot

Run the deterministic 1,000-record pilot against the approved materialized
snapshot. Replace `<materialized-snapshot-id>` only after checking the graph's
`source_snapshots` table.

```bash
./.venv/bin/python main.py curriculum remediate-lexical \
  --db-path data/processed/learning_graph.duckdb \
  --snapshot-id <materialized-snapshot-id> \
  --validation-run-id lexical-53k-pilot-v1 \
  --pilot-size 1000 \
  --pilot-seed lexical-53k-pilot-v1 \
  --batch-size 250
```

The command writes `selection_manifest.json` and `remediation_report.json`
under `data/processed/lexical-53k/lexical-53k-pilot-v1/`.

## Pilot promotion gate

Proceed to the full run only when the pilot has exactly 1,000 dispositions, a
completed remediation checkpoint, no integrity errors, a deterministic rerun
with no additional attempts, and a failure code plus evidence fingerprint for
every quarantine. Recheck the source database SHA-256 and record measured
throughput, peak memory, and graph growth.

## Full run

```bash
./.venv/bin/python main.py curriculum remediate-lexical \
  --db-path data/processed/learning_graph.duckdb \
  --snapshot-id <materialized-snapshot-id> \
  --validation-run-id lexical-53k-full-v1 \
  --batch-size 250
```

If interrupted, resume with the same run ID and `--resume`; do not provide a
new pilot size or seed. The full run produces the validation snapshot and
reconciled report only. AI/human review and verified SQLite publication remain
later phases.

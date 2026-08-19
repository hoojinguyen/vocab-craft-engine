# Lexical 53K Remediation Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run an auditable, resumable deterministic quality remediation pilot over 1,000 stratified lexical inputs, then safely run the same pipeline over all 57,051 rank-1–3500 inputs.

**Architecture:** A deterministic sampling boundary stores the exact pilot inventory and hash in `validation_runs.selection_json`. The remediation service consumes either that fixed inventory or the complete snapshot inventory in committed batches; the existing immutable snapshot, streaming selector, lifecycle, and quarantine tables remain authoritative.

**Tech Stack:** Python 3.15, DuckDB, Pydantic, pytest, Black, Ruff.

---

## File structure

- Create `src/learning/lexical_sampling.py`: deterministic rank/source/POS sample selection and manifest metadata.
- Modify `src/learning/lexical_evidence.py`: validate and list a fixed input inventory.
- Modify `src/learning/lexical_remediation.py`: execute fixed/full inventories with batch/checkpoint semantics.
- Modify `src/learning/lexical_reporting.py`: reconcile selection, checkpoint, disposition, quarantine, and retry metrics.
- Modify `src/pipeline/cli.py` and `src/learning/cli.py`: controlled pilot/full commands and artifact paths.
- Create `tests/test_learning/test_lexical_sampling.py`; modify remediation, reporting, CLI, and contract tests.

### Task 1: Deterministic stratified pilot selection

**Files:**
- Create: `src/learning/lexical_sampling.py`
- Create: `tests/test_learning/test_lexical_sampling.py`

- [ ] **Step 1: Write failing sampling tests**

```python
def test_stratified_pilot_is_stable_and_has_requested_size(graph_catalog):
    seed_inputs(graph_catalog, rank_bands=True, sources=("kaikki", "wordnet"), pos=("noun", "verb"))
    sampler = LexicalPilotSampler(graph_catalog.store)
    first = sampler.select("lexical-snapshot", size=8, seed="pilot-v1")
    second = sampler.select("lexical-snapshot", size=8, seed="pilot-v1")
    assert first.input_ids == second.input_ids
    assert len(first.input_ids) == 8
    assert first.inventory_sha256 == second.inventory_sha256
    assert {row.rank_band for row in first.rows} == {"1-500", "501-1500", "1501-2500", "2501-3500"}

def test_stratified_pilot_rejects_oversized_request(graph_catalog):
    seed_inputs(graph_catalog, rank_bands=True, sources=("kaikki",), pos=("noun",))
    with pytest.raises(ValueError, match="contains only"):
        LexicalPilotSampler(graph_catalog.store).select("lexical-snapshot", size=1000, seed="pilot-v1")
```

- [ ] **Step 2: Verify RED**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_sampling.py -q`

Expected: collection fails because `LexicalPilotSampler` does not exist.

- [ ] **Step 3: Implement the sampler**

Create immutable `PilotRow` and `PilotSelection` dataclasses. `PilotSelection.as_metadata()` returns `kind`, `seed`, ordered `input_ids`, `inventory_sha256`, and stratum counts. Query only the requested snapshot; derive the four rank bands exactly as `1-500`, `501-1500`, `1501-2500`, `2501-3500`; derive source from `source_snapshots.asset_id`; group by `(rank_band, source_asset_id, pos)`.

Allocate each nonempty stratum one item in round-robin order, then allocate remaining slots proportionally by population with lexicographic stratum tie-break. Sort candidates in a stratum by `sha256(f"{seed}:{input_id}")`. Return chosen rows ordered by `frequency_rank, source_word_id, source_definition_id, input_key`; calculate `inventory_sha256` from canonical JSON of those ordered identities. Reject nonpositive or over-population sample sizes.

- [ ] **Step 4: Verify GREEN**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_sampling.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

    git add src/learning/lexical_sampling.py tests/test_learning/test_lexical_sampling.py
    git commit -m "feat(learning): select deterministic lexical pilot samples"

### Task 2: Fixed-inventory remediation and safe resume

**Files:**
- Modify: `src/learning/lexical_evidence.py`
- Modify: `src/learning/lexical_remediation.py`
- Modify: `tests/test_learning/test_lexical_remediation.py`

- [ ] **Step 1: Write failing fixed-inventory tests**

```python
def test_remediation_processes_only_explicit_pilot_inventory(graph_catalog):
    snapshot_id, chosen, unchosen = seed_three_lexical_inputs(graph_catalog)
    report = LexicalRemediationService(graph_catalog.store).run(
        snapshot_id, validation_run_id="pilot-run", input_ids=tuple(chosen),
        selection_metadata={"kind": "stratified_pilot_v1", "input_ids": chosen}, batch_size=1,
    )
    assert report.processed_count == 2
    assert disposition_ids(graph_catalog, "pilot-run") == set(chosen)
    assert unchosen not in disposition_ids(graph_catalog, "pilot-run")

def test_interrupted_fixed_inventory_resumes_without_duplicate_attempts(graph_catalog):
    snapshot_id, chosen, _ = seed_three_lexical_inputs(graph_catalog)
    service = LexicalRemediationService(graph_catalog.store)
    with pytest.raises(RuntimeError, match="interrupted"):
        service.run(snapshot_id, validation_run_id="pilot-run", input_ids=tuple(chosen), batch_size=2, interrupt_after=2)
    report = service.run(snapshot_id, validation_run_id="pilot-run", input_ids=tuple(chosen), batch_size=2)
    assert report.processed_count == len(chosen)
    assert attempt_count(graph_catalog, "pilot-run") == len(chosen)
```

- [ ] **Step 2: Verify RED**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_remediation.py -q`

Expected: FAIL because `run()` has no `input_ids`, `selection_metadata`, or `batch_size` API.

- [ ] **Step 3: Implement the inventory contract**

Add `list_selected_input_ids(snapshot_id, input_ids, after_input_key, limit)` to `LexicalEvidenceRepository`; use bound parameters only and raise `ValueError("selection contains inputs outside snapshot")` when the supplied unique IDs do not all belong to the snapshot. Change `LexicalRemediationService.run` to accept `input_ids`, `selection_metadata`, and positive `batch_size` with default 250.

For a fixed inventory require nonempty unique IDs and metadata whose `input_ids` exactly match; create the validation run with that metadata. On resume compare the stored canonical selection JSON and reject a changed inventory. Process in manifest order and preserve the existing full-snapshot path when no inventory is supplied. Persist each batch’s rankings, dispositions, attempts, and checkpoint in one transaction; advance the checkpoint only after the batch is durable.

- [ ] **Step 4: Verify GREEN**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_remediation.py tests/test_learning/test_lexical_evidence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

    git add src/learning/lexical_evidence.py src/learning/lexical_remediation.py tests/test_learning/test_lexical_remediation.py
    git commit -m "feat(learning): run remediation from fixed input inventories"

### Task 3: Controlled pilot/full CLI and artifacts

**Files:**
- Modify: `src/pipeline/cli.py`
- Modify: `src/learning/cli.py`
- Modify: `tests/test_learning/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_remediate_lexical_pilot_parses_sampling_controls():
    args = parse_arguments(["curriculum", "remediate-lexical", "--snapshot-id", "snapshot-1", "--validation-run-id", "pilot-v1", "--pilot-size", "1000", "--pilot-seed", "lexical-53k-pilot-v1", "--batch-size", "250"])
    assert (args.pilot_size, args.pilot_seed, args.batch_size) == (1000, "lexical-53k-pilot-v1", 250)

def test_remediate_lexical_writes_selection_manifest(tmp_path):
    argv = [
        "remediate-lexical", "--snapshot-id", "snapshot-1",
        "--validation-run-id", "pilot-v1", "--pilot-size", "1000",
        "--pilot-seed", "seed", "--batch-size", "250",
        "--output-dir", str(tmp_path),
    ]
    assert cli.run_curriculum_command(argv) == 0
    assert (tmp_path / "pilot-v1" / "selection_manifest.json").exists()
```

- [ ] **Step 2: Verify RED**

Run: `./.venv/bin/pytest tests/test_learning/test_cli.py -q`

Expected: FAIL because pilot options and selection artifact do not exist.

- [ ] **Step 3: Implement command modes**

Add `--pilot-size`, `--pilot-seed`, `--batch-size` (default 250), and `--output-dir` to `remediate-lexical`. Enforce `--resume` with no fresh `--pilot-size`, pilot requires `--validation-run-id`, and positive sizes/batches. A new pilot calls `LexicalPilotSampler.select`, writes `selection_manifest.json` atomically, and passes IDs/metadata to the service. Full mode passes no inventory and metadata `{"kind": "full_snapshot_v1"}`. Default artifacts to `LEXICAL_53K_RUN_DIR / validation_run_id`; after a completed run write the remediation report. Print run ID and artifact paths.

- [ ] **Step 4: Verify GREEN and commit**

Run: `./.venv/bin/pytest tests/test_learning/test_cli.py -q`

Expected: PASS.

    git add src/pipeline/cli.py src/learning/cli.py tests/test_learning/test_cli.py
    git commit -m "feat(cli): add controlled lexical remediation runs"

### Task 4: Reconciled operational reporting

**Files:**
- Modify: `src/learning/lexical_reporting.py`
- Modify: `tests/test_learning/test_lexical_reporting.py`

- [ ] **Step 1: Write failing reconciliation tests**

```python
def test_report_includes_selection_checkpoint_and_metrics(graph_catalog, tmp_path):
    run_id = seed_completed_pilot_run(graph_catalog)
    report = json.loads(LexicalRunReporter(graph_catalog.store).write_remediation_report(run_id, tmp_path).read_text())
    assert report["selection"]["kind"] == "stratified_pilot_v1"
    assert report["checkpoint"]["completed"] is True
    assert report["counts_by_retry_outcome"] == {}
    assert sum(report["counts_by_state"].values()) == report["input_total"]
    assert report["quarantine_with_missing_reason_count"] == 0

def test_report_rejects_completed_run_without_completed_checkpoint(graph_catalog, tmp_path):
    with pytest.raises(ValueError, match="checkpoint"):
        LexicalRunReporter(graph_catalog.store).write_remediation_report(seed_inconsistent_run(graph_catalog), tmp_path)
```

- [ ] **Step 2: Verify RED**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_reporting.py -q`

Expected: FAIL because selection/checkpoint fields and the consistency guard are absent.

- [ ] **Step 3: Implement fail-closed report fields**

Load `validation_runs.selection_json`, the remediation checkpoint, dispositions, gate failures, attempts filtered by `attempt_number > 1`, and quarantine rows. Reject a completed run without a completed checkpoint, missing disposition for its fixed/full inventory, or a quarantine with empty failure codes or missing evidence fingerprint. Add `selection`, `checkpoint` (`phase`, `processed_count`, `completed`, `last_input_key`), and `quarantine_with_missing_reason_count`, retaining existing rank/source/evidence reconciliations.

- [ ] **Step 4: Verify GREEN and commit**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_reporting.py -q`

Expected: PASS.

    git add src/learning/lexical_reporting.py tests/test_learning/test_lexical_reporting.py
    git commit -m "feat(learning): report reconciled remediation operations"

### Task 5: Integrated pilot gate and operator runbook

**Files:**
- Create: `docs/superpowers/walkthroughs/2026-08-19-lexical-53k-remediation-runbook.md`
- Modify: `tests/test_learning/test_lexical_53k_contract.py`

- [ ] **Step 1: Write the failing end-to-end pilot contract test**

```python
def test_pilot_contract_is_idempotent_and_reportable(graph_catalog, tmp_path):
    snapshot_id = seed_stratified_snapshot(graph_catalog, input_count=1000)
    selection = LexicalPilotSampler(graph_catalog.store).select(snapshot_id, 1000, "pilot-v1")
    service = LexicalRemediationService(graph_catalog.store)
    first = service.run(snapshot_id, validation_run_id="pilot-v1", input_ids=selection.input_ids, selection_metadata=selection.as_metadata(), batch_size=250)
    second = service.run(snapshot_id, validation_run_id="pilot-v1", input_ids=selection.input_ids, selection_metadata=selection.as_metadata(), batch_size=250)
    assert first.processed_count == second.processed_count == 1000
    assert report_reconciles(graph_catalog.store, "pilot-v1", tmp_path)
```

- [ ] **Step 2: Verify RED or expose integration defects**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_53k_contract.py -q`

Expected: FAIL until Tasks 1–4 are integrated; PASS after their integration defects are fixed.

- [ ] **Step 3: Write the operator runbook**

Document this pilot command, replacing the snapshot placeholder only after checking the graph:

```bash
./.venv/bin/python main.py curriculum remediate-lexical --db-path data/processed/learning_graph.duckdb --snapshot-id <materialized-snapshot-id> --validation-run-id lexical-53k-pilot-v1 --pilot-size 1000 --pilot-seed lexical-53k-pilot-v1 --batch-size 250
```

Then document reporting, source SHA recheck, promotion criteria (1,000 reconciled dispositions; completed checkpoint; zero integrity errors; same-run rerun; every quarantine has codes/fingerprint; accepted throughput/disk budget), and the full command using `--validation-run-id lexical-53k-full-v1 --batch-size 250` with no pilot flag. Do not document release export as part of this phase.

- [ ] **Step 4: Run integrated verification**

```bash
./.venv/bin/pytest tests/test_learning/test_lexical_sampling.py tests/test_learning/test_lexical_remediation.py tests/test_learning/test_lexical_reporting.py tests/test_learning/test_lexical_53k_contract.py tests/test_learning/test_cli.py -q
./.venv/bin/pytest tests/test_learning/ -q
./.venv/bin/black --check src/learning/lexical_sampling.py src/learning/lexical_evidence.py src/learning/lexical_remediation.py src/learning/lexical_reporting.py src/learning/cli.py src/pipeline/cli.py tests/test_learning/test_lexical_sampling.py tests/test_learning/test_lexical_remediation.py tests/test_learning/test_lexical_reporting.py tests/test_learning/test_lexical_53k_contract.py tests/test_learning/test_cli.py
./.venv/bin/ruff check src/learning/lexical_sampling.py src/learning/lexical_evidence.py src/learning/lexical_remediation.py src/learning/lexical_reporting.py src/learning/cli.py src/pipeline/cli.py tests/test_learning/test_lexical_sampling.py tests/test_learning/test_lexical_remediation.py tests/test_learning/test_lexical_reporting.py tests/test_learning/test_lexical_53k_contract.py tests/test_learning/test_cli.py
git diff --check
```

Expected: all commands return 0. Black may emit the known Python 3.14/target-3.15 warning but must return 0.

- [ ] **Step 5: Commit**

    git add docs/superpowers/walkthroughs/2026-08-19-lexical-53k-remediation-runbook.md tests/test_learning/test_lexical_53k_contract.py
    git commit -m "docs(plan): add lexical remediation runbook"

## Plan self-review

- Spec coverage: Tasks 1–2 implement stratified selection, immutable inventory, batch checkpointing, idempotence, and resume. Task 3 controls pilot/full operation and artifacts. Task 4 reconciles operational metrics and quarantine reasons. Task 5 binds promotion criteria to commands and integration evidence.
- Scope: AI/human review and verified release export are intentionally excluded.
- Consistency: `PilotSelection.as_metadata()`, `input_ids`, `selection_metadata`, `batch_size`, and the remediation checkpoint phase use the same names throughout.
- Placeholder scan: no TODO/TBD or undefined deferred component remains.

# Reflex Builder Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `enrich_reflex` generate at most 50,000 valid drills of each type quickly, deterministically, idempotently, and with visible batch progress.

**Architecture:** Keep the public builder entry point and replace per-sentence full-pool filtering with run-scoped pools: de-duplicated Vietnamese alternatives and words indexed by length. A local seeded RNG produces repeatable choices; bounded batches are inserted with periodic progress. The owned `reflex_drills` table is cleared before each complete regeneration.

**Tech Stack:** Python 3, DuckDB, pytest, standard-library `logging`, `random`, `json`, and `re`.

---

## File structure

- Modify: `src/enrichment/reflex_builder.py` — candidate-pool preparation, deterministic drill construction, batched persistence, and progress metrics.
- Modify: `tests/test_enrichment/test_reflex_scenarios.py` — focused deterministic behavior coverage for `ReflexBuilder`.
- Modify: `tests/test_transform/test_phase2_deep_audit.py` only if its existing audit assumes an obsolete total-count contract; retain strict non-collision assertions.

### Task 1: Establish bounded and repeatable builder contract

**Files:**

- Modify: `tests/test_enrichment/test_reflex_scenarios.py`
- Modify: `src/enrichment/reflex_builder.py`

- [ ] **Step 1: Write failing cap and idempotency tests**

Add a helper that inserts at least six bilingual sentences and ten eligible words, then add:

```python
def test_reflex_builder_caps_each_drill_type_and_replaces_prior_run(db_mgr):
    seed_test_data(db_mgr)
    builder = ReflexBuilder(seed=7, batch_size=2)

    assert builder.build(db_mgr, max_drills_per_type=2) == 4
    conn = db_mgr.get_connection()
    assert conn.execute(
        "SELECT count(*) FROM reflex_drills WHERE drill_type = 'speed_translation'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM reflex_drills WHERE drill_type = 'cloze'"
    ).fetchone()[0] == 2

    assert builder.build(db_mgr, max_drills_per_type=2) == 4
    assert conn.execute("SELECT count(*) FROM reflex_drills").fetchone()[0] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py::test_reflex_builder_caps_each_drill_type_and_replaces_prior_run -v`

Expected: FAIL because the current builder neither applies the per-type cap nor clears prior records.

- [ ] **Step 3: Write minimal cap and reset implementation**

Give `ReflexBuilder` a constructor and validate configuration before loading data:

```python
class ReflexBuilder:
    def __init__(self, *, seed: int = 0, batch_size: int = 1_000) -> None:
        self._seed = seed
        self._batch_size = batch_size

    def build(self, db_mgr: DuckDBManager, max_drills_per_type: int = 50_000) -> int:
        if max_drills_per_type < 0:
            raise ValueError("max_drills_per_type must be non-negative")
        if self._batch_size < 1:
            raise ValueError("batch_size must be positive")
        conn = db_mgr.get_connection()
        conn.execute("DELETE FROM reflex_drills")
        rng = random.Random(self._seed)
```

Maintain independent `speed_created` and `cloze_created` counters. Do not add a record once a type reaches `max_drills_per_type`; return their sum, not a table-wide count.

- [ ] **Step 4: Run focused tests and formatting**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v && .venv/bin/black src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py && .venv/bin/ruff check src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py`

Expected: tests pass and Ruff reports no findings.

- [ ] **Step 5: Commit the bounded contract**

```bash
git add src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py
git commit -m "fix(enrichment): cap and reset reflex drills"
```

### Task 2: Replace repeated corpus scans with indexed candidate pools

**Files:**

- Modify: `tests/test_enrichment/test_reflex_scenarios.py`
- Modify: `src/enrichment/reflex_builder.py`

- [ ] **Step 1: Write failing validity and deterministic-output tests**

Build two independently seeded temporary databases with the same fixture data and compare ordered `(drill_type, prompt_text, correct_answer, distractors_json)` rows. Assert every stored distractor list has exactly three unique values and excludes the answer:

```python
assert rows_from_first_run == rows_from_second_run
for _, _, answer, payload in rows_from_first_run:
    distractors = json.loads(payload)
    assert len(distractors) == 3
    assert len(set(distractors)) == 3
    assert answer not in distractors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v`

Expected: FAIL because global `random` makes current output non-repeatable and pools can include duplicate distractors.

- [ ] **Step 3: Implement run-scoped pool helpers**

Add small helpers:

```python
def _unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))

def _three_distractors(pool: list[str], answer: str, rng: random.Random) -> list[str] | None:
    candidates = [value for value in pool if value.casefold() != answer.casefold()]
    if len(candidates) < 3:
        return None
    return rng.sample(candidates, 3)
```

Prepare `vi_pool` once from translations plus existing fallbacks, and prepare `words_by_length: dict[int, list[str]]` once from the words query. For cloze combine buckets from `len(target)-2` through `len(target)+2`; use the general pool only if that range has fewer than three valid candidates. Use the local `rng` for target selection and all sampling. Skip and count any drill whose helper returns `None`.

- [ ] **Step 4: Run reflex and phase-2 audits**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py tests/test_transform/test_phase2_deep_audit.py tests/test_transform/test_phase2_verification.py -v`

Expected: PASS, including existing strict non-collision and JSON checks.

- [ ] **Step 5: Commit indexed selection**

```bash
git add src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py
git commit -m "perf(enrichment): precompute reflex candidate pools"
```

### Task 3: Batch persistence and operational progress

**Files:**

- Modify: `tests/test_enrichment/test_reflex_scenarios.py`
- Modify: `src/enrichment/reflex_builder.py`

- [ ] **Step 1: Write failing batch-progress test**

Use `caplog`, `batch_size=2`, and a two-per-type cap:

```python
def test_reflex_builder_logs_progress_after_each_flush(db_mgr, caplog):
    seed_test_data(db_mgr)
    with caplog.at_level("INFO"):
        ReflexBuilder(seed=1, batch_size=2).build(db_mgr, max_drills_per_type=2)
    assert any("reflex progress" in record.message for record in caplog.records)
    assert any("created=2/2" in record.message for record in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py::test_reflex_builder_logs_progress_after_each_flush -v`

Expected: FAIL because the builder has no per-flush progress message and has a fixed 10,000-record threshold.

- [ ] **Step 3: Implement bounded flushes and final summary**

Keep separate pending lists for speed and cloze. Flush one when it reaches `self._batch_size`, then flush remainders. After each successful `insert_batch_fast`, log:

```python
logger.info(
    "reflex progress type=%s sentences=%d created=%d/%d elapsed_s=%.1f",
    drill_type, sentences_examined, created, max_drills_per_type, time.monotonic() - started,
)
```

On insertion failure, raise `RuntimeError(f"reflex batch insert failed for {drill_type}")` with the original exception chained. Emit a completion record containing both created counts and skipped counts.

- [ ] **Step 4: Run focused verification**

Run: `.venv/bin/pytest tests/test_enrichment/test_reflex_scenarios.py -v && .venv/bin/black src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py && .venv/bin/ruff check src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py`

Expected: PASS with no formatter or linter failures.

- [ ] **Step 5: Commit observable batching**

```bash
git add src/enrichment/reflex_builder.py tests/test_enrichment/test_reflex_scenarios.py
git commit -m "feat(enrichment): report reflex batch progress"
```

### Task 4: Full regression and controlled pipeline smoke test

**Files:**

- Modify: no source files expected

- [ ] **Step 1: Run the full suite**

Run: `make test`

Expected: all tests pass. Investigate and fix every regression before proceeding.

- [ ] **Step 2: Verify staging behavior without destructive cleanup**

Run: `make run-tui`

Expected: `enrich_reflex` emits periodic progress, stops each type at 50,000 or after eligible input is exhausted, and reaches a completion summary. Do not run `make clean-db` or delete staging data.

- [ ] **Step 3: Inspect the resulting pipeline log**

Run: `tail -n 120 "$(ls -t logs/pipeline_*.log | head -n 1)"`

Expected: records identify batch counts, elapsed time, completion status, and explicit failure context if applicable.

- [ ] **Step 4: Record verification outcome**

Do not create an empty commit for the smoke test. Include the exact test and
pipeline-log outcomes in the implementation handoff or pull request summary.

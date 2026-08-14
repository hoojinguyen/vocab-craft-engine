# Phrase Extraction Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the all-pairs regex scan in `transform_phrases` with resumable, batch-based n-gram joins that preserve canonical phrase links.

**Architecture:** `PhraseExtractor` builds a finite normalized catalogue, processes sentence-ID batches, produces 2–6 token n-grams, and uses DuckDB equality joins to discover matches. It bulk-inserts phrases and links at each batch boundary, where it also saves checkpoints and emits TUI progress.

**Tech Stack:** Python 3.14, DuckDB, PyArrow, pytest, existing `DuckDBManager`, `ProgressReporter`.

---

## File structure

- Modify: `src/transform/phrase_extractor.py` — normalization, candidates, n-grams, matching, recovery, metrics.
- Modify: `src/pipeline/steps/transform_phrases.py` — pass progress reporter and expose metrics.
- Modify: `tests/test_transform/test_phrase_extractor.py` — unit and integration tests.
- Create: `tests/test_transform/test_phrase_extractor_resume.py` — recovery and progress tests.

### Task 1: Establish normalisation and the structured result

**Files:**

- Modify: `src/transform/phrase_extractor.py`
- Modify: `tests/test_transform/test_phrase_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
from src.transform.phrase_extractor import PhraseExtractor, normalize_phrase_text

def test_normalize_phrase_text_preserves_word_boundaries():
    assert normalize_phrase_text("  Gave-up, now! ") == "gave up now"

def test_phrase_extractor_links_variant_to_canonical_phrase(db_mgr):
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "She GAVE-UP, after the delay.", "source": "test"},
    ])
    result = PhraseExtractor().extract(db_mgr, batch_size=1)

    assert result.phrases_created == 1
    assert db_mgr.fetch_all("SELECT phrase FROM phrases") == [("give up",)]
    assert db_mgr.count_rows("phrase_sentences") == 1
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor.py -k 'normalize_phrase_text or variant_to_canonical' -v`

Expected: FAIL because the public normalizer and structured result do not exist.

- [ ] **Step 3: Implement the public API**

Add near the imports in `src/transform/phrase_extractor.py`:

```python
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")

@dataclass(frozen=True)
class PhraseExtractionResult:
    phrases_created: int
    links_created: int
    sentences_processed: int
    resumed: bool

def normalize_phrase_text(text: str) -> str:
    return " ".join(TOKEN_RE.findall(text.casefold()))
```

Change `extract` to return `PhraseExtractionResult`. Update existing tests that expect the old integer to assert `result.phrases_created`.

- [ ] **Step 4: Verify success**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor.py -k 'normalize_phrase_text or variant_to_canonical' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/transform/phrase_extractor.py tests/test_transform/test_phrase_extractor.py
git commit -m "feat(transform): add phrase extraction result API"
```

### Task 2: Replace all-pairs regex matching with batch n-gram joins

**Files:**

- Modify: `src/transform/phrase_extractor.py`
- Modify: `tests/test_transform/test_phrase_extractor.py`

- [ ] **Step 1: Write failing candidate and idempotency tests**

```python
def test_phrase_extractor_matches_dynamic_multiword_lemma_across_batches(db_mgr):
    db_mgr.insert_batch_fast("words", [
        {"lemma": "at home", "pos": "phrase", "source": "test"},
        {"lemma": "too many words for this candidate catalogue", "pos": "phrase", "source": "test"},
    ])
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "Nobody was home.", "source": "test"},
        {"text_en": "We stayed at home.", "source": "test"},
        {"text_en": "AT HOME is where I work.", "source": "test"},
    ])

    first = PhraseExtractor().extract(db_mgr, batch_size=1)
    second = PhraseExtractor().extract(db_mgr, batch_size=1)

    assert first.sentences_processed == 3
    assert db_mgr.fetch_all("SELECT phrase FROM phrases WHERE phrase = 'at home'") == [("at home",)]
    assert db_mgr.count_rows("phrase_sentences") == 2
    assert second.links_created == 0
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor.py::test_phrase_extractor_matches_dynamic_multiword_lemma_across_batches -v`

Expected: FAIL because the old extractor has no batching or structured result.

- [ ] **Step 3: Implement candidate and batch helpers**

Add the following methods to `PhraseExtractor`:

```python
CHECKPOINT_STEP = "transform_phrases"

def _build_candidates(self, db_mgr: DuckDBManager) -> list[dict[str, str]]:
    """Return deterministic surface-to-canonical candidate rows."""

def _candidate_signature(self, candidates: list[dict[str, str]]) -> str:
    payload = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _sentence_ngrams(self, sentence_id: int, text_en: str) -> list[dict[str, object]]:
    tokens = normalize_phrase_text(text_en).split()
    return [
        {"sentence_id": sentence_id, "surface": " ".join(tokens[start:start + width])}
        for width in range(2, 7)
        for start in range(0, len(tokens) - width + 1)
    ]

def _match_batch(self, db_mgr: DuckDBManager, sentences: list[tuple[int, str]]) -> list[tuple[str, str, str, str, int]]:
    """Register batch n-grams and DuckDB-join them to the active candidates."""
```

`_build_candidates` must add curated canonical forms and variants, mapping every variant to its canonical phrase. Add `words.lemma` candidates only when their normalized token count is 2–6; set their type to `collocation` and definition to `Expression: {canonical}`. Deduplicate deterministic rows by `(surface, phrase)`.

At extraction start, register the candidates in a unique temporary Arrow relation. Fetch sentences only with:

```sql
SELECT id, text_en
FROM sentences
WHERE id > ?
ORDER BY id
LIMIT ?
```

For each batch, register `_sentence_ngrams` in a second unique temporary Arrow relation and execute:

```sql
SELECT DISTINCT c.phrase, c.phrase_type, c.definition_en, c.cefr_level, n.sentence_id
FROM {ngram_table} AS n
JOIN {candidate_table} AS c ON c.surface = n.surface
```

Bulk insert matched canonical phrases first. Query IDs only for that batch's phrases with a parameterized `IN` clause, then bulk insert `phrase_sentences`. Always unregister each temporary relation in `finally`. Remove the old `re.Pattern.search` loop, `fetch_all("SELECT id, text_en FROM sentences")`, `seen_links`, and all-process link accumulation.

- [ ] **Step 4: Verify matching and regression behavior**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor.py tests/test_transform/test_phase2_deep_audit.py -v`

Expected: PASS, including canonical matches for `break down`, `give up`, and `make a decision`.

- [ ] **Step 5: Commit**

```bash
git add src/transform/phrase_extractor.py tests/test_transform/test_phrase_extractor.py
git commit -m "perf(transform): batch phrase ngram matching"
```

### Task 3: Make batch work resumable and observable

**Files:**

- Modify: `src/transform/phrase_extractor.py`
- Modify: `src/pipeline/steps/transform_phrases.py`
- Create: `tests/test_transform/test_phrase_extractor_resume.py`

- [ ] **Step 1: Write failing resume and progress tests**

```python
def test_phrase_extractor_resumes_after_saved_batch_checkpoint(db_mgr):
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "I will give up.", "source": "test"},
        {"text_en": "They gave up.", "source": "test"},
        {"text_en": "Never give up.", "source": "test"},
    ])
    extractor = PhraseExtractor()
    signature = extractor._candidate_signature(extractor._build_candidates(db_mgr))
    db_mgr.save_checkpoint(
        "transform_phrases", "sentence_1", 1,
        json.dumps({"last_sentence_id": 1, "signature": signature,
                    "phrases_created": 1, "links_created": 1}),
    )

    result = extractor.extract(db_mgr, batch_size=1)

    assert result.resumed is True
    assert result.sentences_processed == 2
    assert db_mgr.count_rows("phrase_sentences") == 2

def test_phrase_extractor_emits_batch_progress(db_mgr):
    events = []
    reporter = ProgressReporter(
        lambda step, current, total, message: events.append((step, current, total, message)),
        throttle_interval=0,
    )
    # Seed three curated-MWE matching sentences before this call.
    PhraseExtractor().extract(db_mgr, batch_size=1, progress=reporter)

    assert [event[1] for event in events] == [1, 2, 3]
    assert all("ETA=" in event[3] for event in events)
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor_resume.py -v`

Expected: FAIL because checkpoints are not read and progress is not emitted.

- [ ] **Step 3: Implement recovery and progress**

After candidate construction, read `db_mgr.get_last_checkpoint(self.CHECKPOINT_STEP)`. Parse its JSON metadata. Resume only when stored `signature` equals the current candidate signature; otherwise call `db_mgr.clear_checkpoints(self.CHECKPOINT_STEP)` and start at ID zero.

After every successful batch insert, call:

```python
db_mgr.save_checkpoint(
    self.CHECKPOINT_STEP,
    f"sentence_{last_sentence_id}",
    sentences_processed,
    json.dumps({
        "last_sentence_id": last_sentence_id,
        "signature": signature,
        "phrases_created": phrases_created,
        "links_created": links_created,
    }, sort_keys=True),
)
elapsed = max(time.monotonic() - started, 0.001)
rate = sentences_processed / elapsed
eta_seconds = int(remaining_sentences / rate) if rate else 0
progress.emit_progress(
    self.CHECKPOINT_STEP, completed_sentences, total_sentences,
    f"sentences={completed_sentences}/{total_sentences}; links={links_created}; "
    f"rate={rate:.1f}/s; ETA={eta_seconds}s",
)
```

Clear the checkpoint only after final inserts and the final progress event succeed. Leave it intact on an exception. Update `TransformPhrasesStep.run`:

```python
result = PhraseExtractor().extract(ctx.db, progress=ctx.progress_reporter)
return StepResult(
    step_name=self.name,
    status=StepStatus.SUCCESS,
    items_processed=result.phrases_created,
    data_metrics={
        "links_created": result.links_created,
        "sentences_processed": result.sentences_processed,
    },
)
```

- [ ] **Step 4: Verify recovery and concurrent-transform regression**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor_resume.py tests/test_transform/test_phrase_extractor.py tests/test_pipeline/test_ingestor_concurrency_fk.py -v`

Expected: PASS; resume processes only sentences after the checkpoint and duplicate links are absent.

- [ ] **Step 5: Commit**

```bash
git add src/transform/phrase_extractor.py src/pipeline/steps/transform_phrases.py tests/test_transform/test_phrase_extractor_resume.py
git commit -m "feat(transform): resume phrase extraction batches"
```

### Task 4: Run verification and safely resume the real pipeline

**Files:**

- Modify: `tests/test_transform/test_phrase_extractor.py`

- [ ] **Step 1: Add a multi-batch regression fixture**

```python
def test_phrase_extractor_processes_large_fixture_in_small_batches(db_mgr):
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": f"We will give up only after test {index}.", "source": "test"}
        for index in range(101)
    ])

    result = PhraseExtractor().extract(db_mgr, batch_size=10)

    assert result.sentences_processed == 101
    assert result.links_created == 101
    assert db_mgr.count_rows("phrase_sentences") == 101
```

- [ ] **Step 2: Run all affected tests**

Run: `.venv/bin/pytest tests/test_transform/test_phrase_extractor.py tests/test_transform/test_phrase_extractor_resume.py tests/test_transform/test_phase2_deep_audit.py tests/test_transform/test_phase2_verification.py tests/test_pipeline/test_ingestor_concurrency_fk.py -v`

Expected: PASS.

- [ ] **Step 3: Format and lint**

Run: `.venv/bin/black src/transform/phrase_extractor.py src/pipeline/steps/transform_phrases.py tests/test_transform/test_phrase_extractor.py tests/test_transform/test_phrase_extractor_resume.py && .venv/bin/ruff check src/transform/phrase_extractor.py src/pipeline/steps/transform_phrases.py tests/test_transform/test_phrase_extractor.py tests/test_transform/test_phrase_extractor_resume.py`

Expected: Black exits 0 and Ruff reports no violations.

- [ ] **Step 4: Stop the obsolete run and smoke-test only after code verification**

Stop the current TUI in its original terminal with `Ctrl-C`. Do not delete `data/processed/staging.duckdb`. Then run:

```bash
make resume
```

Expected: the log reports batch progress with nonzero rate and ETA; completed upstream data remains available; no all-pairs regex scan executes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_transform/test_phrase_extractor.py
git commit -m "test(transform): cover batched phrase extraction"
```

## Plan self-review

- **Spec coverage:** Tasks 1–2 cover canonical forms, variants, dynamic 2–6 token candidates, equality joins, bounded memory, and idempotency. Task 3 covers checkpoint signatures, recovery, errors before checkpoints, log/TUI progress, and result metrics. Task 4 covers regression checks and safe operational restart.
- **Placeholder scan:** No unresolved markers or generic testing instructions remain.
- **Type consistency:** `PhraseExtractionResult`, `normalize_phrase_text`, `PhraseExtractor.extract`, `CHECKPOINT_STEP`, `_build_candidates`, `_candidate_signature`, `_sentence_ngrams`, and `_match_batch` are introduced before later tasks use them.

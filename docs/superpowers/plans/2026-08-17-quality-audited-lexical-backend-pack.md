# Quality-Audited Lexical Backend Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a deterministic SQLite lexical pack that the application can query offline, containing only reviewed word-sense records with verified provenance, Vietnamese meaning, IPA evidence, and bilingual examples.

**Architecture:** Keep `english_dataset.db` immutable as a reference artifact. A dedicated learning graph records source snapshots, raw lexical bundles, candidates, gate results, and review decisions; a separate composer exports only approved senses that passed a named validation run. The first pack deliberately excludes dialogue, audio, phrase search, and full-text search, because those features require their own quality contracts.

**Tech Stack:** Python 3.14, DuckDB, SQLite, Pydantic, PyYAML, pytest.

---

## Scope and sequencing

This plan implements the first vertical slice from the approved design: single-word
lexical senses with one or more bilingual example sentences. It does not change
the legacy ingestion DAG or mutate `data/output/english_dataset.db`.

The next independent plans are: (1) approved phrase and sentence-search packs,
(2) dialogue/scenario curation, and (3) audio asset generation and verification.
None of those may be added to this implementation as incidental work.

## File structure

| File | Responsibility |
| --- | --- |
| `src/learning/models.py` | Candidate lifecycle and source-snapshot input models. |
| `src/learning/schema.py` | Migration 003 for source snapshots, validation runs, candidate gate results, and `validated` candidate state. |
| `src/learning/catalog.py` | Content-addressed registration of a local source snapshot. |
| `src/learning/repository.py` | Idempotent candidate creation, validation-state transitions, review of validated candidates, and query helpers. |
| `src/learning/sqlite_reference_importer.py` | Read-only streaming importer for the selected lexical slice from `english_dataset.db`. |
| `src/learning/quality.py` | Reusable payload validation plus the `sense` quality contract. |
| `src/learning/lexical_audit.py` | Projection of raw bundles into sense candidates, deterministic gate evaluation, quarantine, and JSON audit report generation. |
| `src/learning/lexical_pack.py` | Compose approved, gate-passing senses into an immutable backend pack model. |
| `src/learning/lexical_exporter.py` | Write relational SQLite/JSON/manifest artifacts without overwriting a published directory. |
| `src/learning/cli.py`, `src/pipeline/cli.py` | Commands for snapshot registration, lexical import/audit/review/report/composition. |
| `docs/learning-graph-operations.md` | Operator workflow and published-pack release checklist. |
| `tests/test_learning/` | Isolated migrations, importer, gate, repository, CLI, composition, exporter, and end-to-end tests. |

### Task 1: Add provenance and validation-run persistence

**Files:**
- Modify: `src/learning/models.py:54-125`
- Modify: `src/learning/schema.py:8-250`
- Modify: `src/learning/catalog.py:1-194`
- Test: `tests/test_learning/test_models.py`
- Test: `tests/test_learning/test_schema.py`
- Test: `tests/test_learning/test_catalog.py`

- [ ] **Step 1: Write failing model and migration tests**

Add tests proving that a source snapshot records a real local file checksum, that
candidate state accepts `validated`, and that migration 003 creates the three
audit tables.

```python
def test_source_snapshot_requires_the_registered_asset_checksum(tmp_path, catalog):
    source_file = tmp_path / "reference.db"
    source_file.write_bytes(b"reference snapshot")
    checksum = hashlib.sha256(source_file.read_bytes()).hexdigest()
    catalog.register_source(_approved_source().model_copy(update={"sha256": checksum}))

    snapshot_id = catalog.record_source_snapshot(
        "approved-source", source_file, "2026-08-17T00:00:00+00:00"
    )

    assert catalog.store.fetch_value(
        "SELECT file_sha256 FROM source_snapshots WHERE snapshot_id = ?",
        [snapshot_id],
    ) == checksum


def test_migration_v3_creates_validation_tables_and_validated_candidate_state():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)

    assert {"source_snapshots", "validation_runs", "candidate_gate_results"}.issubset(
        {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    )
    conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["fixture-source", "Fixture", "https://example.test", "1", "a" * 64,
         "LicenseRef-Test", "https://example.test/license", "Fixture", True, "approved"],
    )
    conn.execute(
        "INSERT INTO raw_reference_records VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)",
        ["raw-1", "fixture-source", "fixture:1", "bundle", "{}", "b" * 64, "test"],
    )
    conn.execute(
        "INSERT INTO content_candidates VALUES (?, ?, ?, ?, ?, ?, 'validated', current_timestamp)",
        ["candidate-1", "raw-1", "sense", "{}", "{}", 1.0],
    )
    assert conn.execute("SELECT state FROM content_candidates WHERE candidate_id = 'candidate-1'").fetchone() == ("validated",)
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `./.venv/bin/pytest tests/test_learning/test_models.py tests/test_learning/test_schema.py tests/test_learning/test_catalog.py -v`

Expected: FAIL because `record_source_snapshot`, the migration tables, and the
`validated` state do not exist.

- [ ] **Step 3: Add the models and migration 003**

Keep `ReviewState` for review decisions and add a separate candidate-state enum.
Do not add `validated` to `ReviewState`, because source assets and review decisions
must continue to accept only their existing state sets.

```python
class CandidateState(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class SourceSnapshotInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    local_path: Path
    retrieved_at: datetime
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

Add `MIGRATION_003` and append `(3, MIGRATION_003)` to `MIGRATIONS`. Rebuild the
five tables that depend on `content_candidates` using the same snapshot/restore
pattern as migration 002, then recreate `content_candidates` with this check:

```sql
CHECK (state IN ('candidate','validated','approved','rejected','quarantined'))
```

Create these tables in migration 003:

```sql
CREATE TABLE source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES source_assets(asset_id),
    local_path TEXT NOT NULL,
    retrieved_at TIMESTAMP NOT NULL,
    file_sha256 TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(asset_id, file_sha256)
);
CREATE TABLE validation_runs (
    validation_run_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    policy_version TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    completed_at TIMESTAMP
);
CREATE TABLE candidate_gate_results (
    validation_run_id TEXT NOT NULL REFERENCES validation_runs(validation_run_id),
    candidate_id TEXT NOT NULL REFERENCES content_candidates(candidate_id),
    gate_code TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, candidate_id, gate_code)
);
```

Implement `SourceCatalog.record_source_snapshot()` so it reads the file in
64 KiB chunks, verifies the SHA-256 equals `source_assets.sha256`, and inserts
or returns the existing `(asset_id, file_sha256)` row inside
`_retry_catalog_write`.

- [ ] **Step 4: Run focused tests and the current learning suite**

Run: `./.venv/bin/pytest tests/test_learning/test_models.py tests/test_learning/test_schema.py tests/test_learning/test_catalog.py -v`

Expected: PASS. Confirm migration 001/002 compatibility tests still pass and
the new migration is included by `LearningGraphStore.initialize()`.

- [ ] **Step 5: Commit the persistence foundation**

```bash
git add src/learning/models.py src/learning/schema.py src/learning/catalog.py \
  tests/test_learning/test_models.py tests/test_learning/test_schema.py \
  tests/test_learning/test_catalog.py
git commit -m "feat(learning): persist source snapshots and validation runs"
```

### Task 2: Make candidate validation and review stateful and idempotent

**Files:**
- Modify: `src/learning/repository.py:17-345`
- Modify: `tests/test_learning/conftest.py:1-300`
- Test: `tests/test_learning/test_repository.py`

- [ ] **Step 1: Write failing repository tests**

Cover deterministic candidate creation, the candidate-to-validated transition,
and a human review of a validated candidate.

```python
def test_create_candidate_returns_existing_id_for_same_raw_payload(graph_catalog):
    repository = ContentRepository(graph_catalog.store)
    raw_id = graph_catalog.record_raw_snapshot("human-authored-a0", "word:book", {"id": 1})
    payload = {"stable_key": "sense.book.noun.123456789abc", "definition_en": "a set of pages"}

    first = repository.create_candidate(raw_id, "sense", payload, {"source": "fixture"}, 1.0)
    second = repository.create_candidate(raw_id, "sense", payload, {"source": "fixture"}, 1.0)

    assert second == first


def test_validated_candidate_can_be_approved_but_candidate_cannot(graph_catalog):
    repository = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repository, graph_catalog)

    with pytest.raises(ValueError, match="validated"):
        repository.review_candidate(candidate_id, "approved", "editor-1", "Reviewed")

    repository.mark_candidate_validated(candidate_id)
    assert repository.review_candidate(candidate_id, "approved", "editor-1", "Reviewed")
```

- [ ] **Step 2: Run the focused repository tests and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_repository.py -v`

Expected: FAIL because `create_candidate` always generates a new UUID and
`mark_candidate_validated` does not exist.

- [ ] **Step 3: Implement the repository contract**

Add a candidate lookup before the existing insert. It must compare the canonical
normalized payload string, content type, and raw record ID; it must not dedupe
different senses that share a word record.

```python
existing = connection.execute(
    """
    SELECT candidate_id FROM content_candidates
    WHERE raw_record_id = ? AND content_type = ? AND normalized_payload_json = ?
    """,
    [raw_record_id, content_type, canonical_json(revision_input.payload)],
).fetchone()
if existing is not None:
    return str(existing[0])
```

Add `mark_candidate_validated(candidate_id: str) -> None`. It may transition
only `candidate -> validated`; all other source states raise `ValueError`.
Change `review_candidate()` so approval requires `CandidateState.VALIDATED`;
rejection and quarantine accept either `candidate` or `validated`. Keep the
existing immutable revision and review insertion logic for approval.

Add `candidate_payload(candidate_id: str) -> dict[str, object]` and
`candidates_for_validation_run(validation_run_id: str) -> list[dict[str, object]]`
so later services do not issue ad-hoc SQL outside the repository.

Update the shared learning fixtures and existing repository/vertical-slice tests
so candidates are explicitly marked `validated` before an approval review; this
keeps the new lifecycle rule visible in every test that seeds approved content.

- [ ] **Step 4: Run focused tests and regression tests**

Run: `./.venv/bin/pytest tests/test_learning/test_repository.py tests/test_learning/test_schema.py -v`

Expected: PASS. Verify an approved revision still has a matching candidate review
foreign key and rejected candidates still create no revision.

- [ ] **Step 5: Commit candidate lifecycle changes**

```bash
git add src/learning/repository.py tests/test_learning/test_repository.py
git commit -m "feat(learning): require validated candidates before approval"
```

### Task 3: Import a bounded lexical slice from SQLite without mutating it

**Files:**
- Create: `src/learning/sqlite_reference_importer.py`
- Modify: `src/learning/catalog.py:87-168`
- Test: `tests/test_learning/test_sqlite_reference_importer.py`

- [ ] **Step 1: Write failing importer tests against a temporary SQLite database**

Create the minimal legacy tables in a fixture. Include one eligible `book` noun,
one proper name, one rank-4000 noun, bilingual definitions, and three sentence
links. The test proves that only `book` is copied, its payload is complete, and
rerunning produces no second raw record.

```python
def test_import_vertical_slice_snapshots_only_policy_eligible_lexical_bundles(
    catalog, legacy_sqlite, approved_snapshot_id
):
    report = SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        legacy_sqlite, approved_snapshot_id, "run-2026-08-17"
    )

    assert report.eligible_words == 1
    assert report.imported_raw_records == 1
    payload = json.loads(catalog.store.fetch_value("SELECT payload_json FROM raw_reference_records"))
    assert payload["word"]["lemma"] == "book"
    assert payload["definitions"][0]["definition_vi"] == "quyển sách"
    assert payload["examples"] == [{"text_en": "Read this book.", "text_vi": "Hãy đọc quyển sách này.", "source": "tatoeba"}]
```

- [ ] **Step 2: Run the importer test and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_sqlite_reference_importer.py -v`

Expected: FAIL because `SQLiteLexicalReferenceImporter` does not exist.

- [ ] **Step 3: Implement the read-only importer and batch raw append**

Create a policy value object in the new module. Keep the policy fixed for this
first pack; do not expose arbitrary query fragments through the CLI.

```python
FIRST_LEXICAL_POS = frozenset({
    "noun", "verb", "adj", "adv", "prep", "pron", "det", "conj", "intj", "article", "num",
})
FIRST_LEXICAL_LEMMA = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
MAX_FREQUENCY_RANK = 3500
MAX_EXAMPLES_PER_WORD = 3
```

Open the legacy DB with `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` and
set `PRAGMA query_only = ON`. Select `words` by rank, filter POS and normalized
lemma in Python, then fetch definitions and at most three linked bilingual
sentences ordered by `sentence_id`. The importer must never run `INSERT`,
`UPDATE`, `DELETE`, `VACUUM`, or a non-read-only pragma against the legacy DB.

Store one raw record per selected word with:

```python
payload = {
    "word": {
        "legacy_word_id": word_id, "lemma": lemma, "pos": pos,
        "frequency_rank": frequency_rank, "cefr_level": cefr_level,
        "ipa_uk": ipa_uk, "ipa_us": ipa_us, "source": source,
    },
    "definitions": definitions,
    "examples": examples,
}
```

Add `SourceCatalog.append_raw_records(records: Sequence[RawRecordInput])` so
the importer writes batches of 250 records in one graph transaction while
retaining the existing content-addressed idempotence check for each external key.
Use external keys `sqlite-lexical:{legacy_word_id}` and record type
`sqlite_lexical_bundle`.

- [ ] **Step 4: Run importer tests, including idempotence**

Run: `./.venv/bin/pytest tests/test_learning/test_sqlite_reference_importer.py tests/test_learning/test_catalog.py -v`

Expected: PASS. Confirm the source SQLite file hash and its modification time
are unchanged after import.

- [ ] **Step 5: Commit the immutable SQLite import path**

```bash
git add src/learning/sqlite_reference_importer.py src/learning/catalog.py \
  tests/test_learning/test_sqlite_reference_importer.py
git commit -m "feat(learning): import bounded lexical bundles from SQLite"
```

### Task 4: Project lexical senses and enforce their quality gates

**Files:**
- Modify: `src/learning/quality.py:26-425`
- Create: `src/learning/lexical_audit.py`
- Test: `tests/test_learning/test_quality.py`
- Test: `tests/test_learning/test_lexical_audit.py`

- [ ] **Step 1: Write failing quality and audit tests**

Use three lexical bundles: one complete sense, one English-passthrough
translation, and one with no IPA. Assert that only the complete sense is marked
validated and that the remaining candidates become quarantined with stable gate
codes.

```python
def test_sense_gate_rejects_passthrough_translation_and_missing_ipa():
    report = QualityGate().validate_payload("sense", {
        "stable_key": "sense.book.noun.123456789abc",
        "lemma": "book", "pos": "noun", "frequency_rank": 100,
        "cefr_level": "A1", "cefr_method": "frequency_rank_v1",
        "definition_en": "a set of pages", "definition_vi": "a set of pages",
        "ipa_us": None, "ipa_uk": None, "ipa_source": None,
        "examples": [{"text_en": "Read this book.", "text_vi": "Hãy đọc quyển sách này.", "source": "tatoeba"}],
    })

    assert {failure.code for failure in report.failures} == {
        "sense.translation_passthrough", "sense.ipa_missing"
    }
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_quality.py tests/test_learning/test_lexical_audit.py -v`

Expected: FAIL because `validate_payload`, `_validate_sense`, and
`LexicalAuditService` do not exist.

- [ ] **Step 3: Implement reusable payload validation and the lexical audit service**

Refactor `QualityGate.validate_revision()` to call a new payload-only method;
candidate validation must not need to pretend that an unreviewed candidate is an
approved revision.

```python
def validate_payload(
    self, content_type: str, payload: dict[str, Any], revision_id: str | None = None
) -> GateReport:
    report = GateReport()
    if not payload.get("stable_key"):
        report.add("revision.stable_key_missing", "A stable_key is required", revision_id)
    validator = getattr(self, f"_validate_{content_type}", None)
    if validator is not None:
        validator(payload, report, revision_id)
    return report
```

Implement `_validate_sense()` with exactly these gate codes:

```text
sense.lemma_invalid
sense.pos_invalid
sense.frequency_rank_invalid
sense.cefr_mismatch
sense.definition_missing
sense.translation_missing
sense.translation_placeholder
sense.translation_passthrough
sense.ipa_missing
sense.ipa_unverified
sense.example_missing
sense.example_alignment_invalid
```

The CEFR mapping is fixed: ranks `1-500=A1`, `501-1500=A2`,
`1501-3500=B1`. A Vietnamese translation fails when empty, begins with `[VI]`,
or equals the English definition after casefolding and whitespace normalization.
An example fails when either language is blank, both normalized strings are
equal, its English/Vietnamese length ratio is outside `0.25..4.0`, or its source
is blank. IPA passes only when at least one variant exists, `ipa_source` is
non-empty, and `ipa_confidence >= 0.8`.

`LexicalAuditService` must project one `sense` candidate per definition using a
stable key based on the normalized lemma, POS, and first 12 characters of the
definition SHA-256:

```python
stable_key = f"sense.{lemma}.{pos}.{definition_hash[:12]}"
payload = {
    "stable_key": stable_key,
    "lemma": lemma,
    "pos": pos,
    "frequency_rank": word["frequency_rank"],
    "cefr_level": cefr_for_rank(word["frequency_rank"]),
    "cefr_method": "frequency_rank_v1",
    "definition_en": definition["definition_en"],
    "definition_vi": definition["definition_vi"],
    "ipa_uk": word["ipa_uk"],
    "ipa_us": word["ipa_us"],
    "ipa_source": word["source"] if word["ipa_uk"] or word["ipa_us"] else None,
    "ipa_confidence": 0.8 if word["source"] == "kaikki" and (word["ipa_uk"] or word["ipa_us"]) else 0.0,
    "examples": bundle["examples"],
    "source_asset_id": source_asset_id,
}
```

It creates candidates idempotently, writes one `validation_runs` row containing
the fixed policy JSON, persists every `GateFailure` or successful gate in
`candidate_gate_results`, marks all-passing candidates `validated`, and
quarantines every failing candidate with reviewer ID `validator:lexical-v1` and
the comma-separated gate codes as rationale. Return a report with counts by
candidate state and gate code.

- [ ] **Step 4: Run quality/audit tests and verify deterministic output**

Run: `./.venv/bin/pytest tests/test_learning/test_quality.py tests/test_learning/test_lexical_audit.py tests/test_learning/test_repository.py -v`

Expected: PASS. Run the audit twice in the test and assert that the second run
creates no duplicate candidates or raw records while producing the same gate
counts.

- [ ] **Step 5: Commit lexical quality enforcement**

```bash
git add src/learning/quality.py src/learning/lexical_audit.py \
  tests/test_learning/test_quality.py tests/test_learning/test_lexical_audit.py
git commit -m "feat(learning): audit lexical candidates with quality gates"
```

### Task 5: Expose the controlled operator workflow through the curriculum CLI

**Files:**
- Modify: `src/pipeline/cli.py:62-93`
- Modify: `src/learning/cli.py:21-73`
- Test: `tests/test_learning/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add parser and command tests for the six required actions: source snapshot,
lexical import, audit, report, composition, and a human review decision.

```python
def test_curriculum_lexical_commands_use_only_the_learning_graph(tmp_path, legacy_sqlite, manifest):
    graph = tmp_path / "graph.duckdb"
    assert run_curriculum_command(["register-source", "--db-path", str(graph), "--manifest", str(manifest)]) == 0
    assert run_curriculum_command([
        "snapshot-source", "--db-path", str(graph), "--asset-id", "legacy-sqlite",
        "--local-path", str(legacy_sqlite), "--retrieved-at", "2026-08-17T00:00:00+00:00",
    ]) == 0
```

- [ ] **Step 2: Run CLI tests and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_cli.py -v`

Expected: FAIL because the lexical subcommands are absent.

- [ ] **Step 3: Add explicit subcommands and dispatch**

Add these curriculum commands and no legacy-pipeline flags:

```text
snapshot-source --asset-id --local-path --retrieved-at
snapshot-lexical-reference --reference-db --snapshot-id --import-run-id
audit-lexical --snapshot-id
review-candidate --candidate-id --decision {approved,rejected,quarantined} --reviewer-id --rationale
report-lexical --validation-run-id --output-path
compose-lexical --validation-run-id --pack-id --version --cefr-level {A1,A2,B1} --output-dir
```

The importer and audit may inspect ranks through 3500, but the composer selects
one CEFR band per pack. The first published pack is `lexical-a1`, so the
approved-design minimum of 30 records is enforced for every populated
source/entity cell in that pack.

`audit-lexical` prints its validation-run ID. `review-candidate` delegates to
`ContentRepository.review_candidate()` and rejects an unvalidated approval with
exit code 2. `report-lexical` writes deterministic, sorted JSON with candidate
state counts, gate-code counts, and the candidate IDs/payload summaries needing
human review. Each command opens only `learning_graph.duckdb` for writes; the
reference SQLite path is opened only by `SQLiteLexicalReferenceImporter` in
read-only mode.

- [ ] **Step 4: Run CLI tests and smoke-test help output**

Run: `./.venv/bin/pytest tests/test_learning/test_cli.py -v`

Then run: `./.venv/bin/python main.py curriculum --help`

Expected: PASS and help lists all six lexical commands. Confirm `staging.duckdb`
and `english_dataset.db` checksums are unchanged by the test.

- [ ] **Step 5: Commit the operator CLI**

```bash
git add src/pipeline/cli.py src/learning/cli.py tests/test_learning/test_cli.py
git commit -m "feat(learning): add lexical curation commands"
```

### Task 6: Compose and export an offline lexical backend pack

**Files:**
- Create: `src/learning/lexical_pack.py`
- Create: `src/learning/lexical_exporter.py`
- Test: `tests/test_learning/test_lexical_pack.py`
- Test: `tests/test_learning/test_lexical_exporter.py`

- [ ] **Step 1: Write failing composition and export tests**

Build thirty approved, validated senses from one source asset and one
validated-but-unapproved sense in a temporary graph. Assert that composition
includes only the approved senses and export creates queryable SQLite, JSON,
SHA-256, and manifest files.

```python
def test_lexical_pack_contains_only_approved_senses_from_the_validation_run(graph_store):
    pack = LexicalPackComposer(ContentRepository(graph_store)).compose(
        "validation-run-1", "lexical-a1", "0.1.0", "A1"
    )

    assert len(pack.senses) == 30
    assert "badword" not in {sense["lemma"] for sense in pack.senses}
    assert pack.quality_report["passed"] is True


def test_lexical_export_writes_indexed_offline_artifacts(tmp_path, lexical_pack):
    result = LexicalPackExporter().export(lexical_pack, tmp_path / "lexical-a1")

    connection = sqlite3.connect(result.sqlite_path)
    assert connection.execute("SELECT definition_vi FROM senses WHERE lemma = 'lexaa'").fetchone() == ("nghĩa của lexaa",)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
```

- [ ] **Step 2: Run the pack tests and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_pack.py tests/test_learning/test_lexical_exporter.py -v`

Expected: FAIL because the lexical composer and exporter do not exist.

- [ ] **Step 3: Implement composition and a relational SQLite export**

`LexicalPackComposer.compose(validation_run_id, pack_id, version, cefr_level)`
selects only `sense` revisions where the candidate is `approved`, every gate
result in the given run passed, and `payload.cefr_level` equals the requested
band. It raises `ValueError` if the selection is empty, a selected payload lacks
definition/IPA/example, or a populated `source_asset_id` has fewer than 30
individually approved senses in that band. Individual approval is the recorded
human acceptance sample for this first lexical pack. Sort senses by
`(frequency_rank, lemma, pos, stable_key)` and examples by
`(sense_id, rank, text_en)`.

`LexicalPackExporter` refuses an existing output directory and writes:

```sql
CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE senses (
    sense_id TEXT PRIMARY KEY, stable_key TEXT UNIQUE NOT NULL,
    lemma TEXT NOT NULL, pos TEXT NOT NULL, definition_en TEXT NOT NULL,
    definition_vi TEXT NOT NULL, frequency_rank INTEGER NOT NULL,
    cefr_level TEXT NOT NULL, ipa_uk TEXT, ipa_us TEXT,
    source_asset_id TEXT NOT NULL
);
CREATE TABLE sense_examples (
    sense_id TEXT NOT NULL REFERENCES senses(sense_id), rank INTEGER NOT NULL,
    text_en TEXT NOT NULL, text_vi TEXT NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY(sense_id, rank)
);
CREATE INDEX idx_senses_lemma_pos ON senses(lemma, pos);
CREATE INDEX idx_senses_frequency ON senses(frequency_rank);
CREATE INDEX idx_examples_sense ON sense_examples(sense_id, rank);
```

Write `lexical.db`, `lexical.json`, `manifest.json`, and `lexical.db.sha256`.
The manifest contains pack/version, validation-run ID, approved-sense count,
quality summary, source attributions, and SHA-256/size for both emitted data
files. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` before
writing the manifest; abort and remove the temporary directory on failure.

- [ ] **Step 4: Run focused export tests and inspect the query plan**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_pack.py tests/test_learning/test_lexical_exporter.py -v`

Expected: PASS. In the exporter test, assert `EXPLAIN QUERY PLAN SELECT * FROM senses WHERE lemma = 'book'` contains `idx_senses_lemma_pos`.

- [ ] **Step 5: Commit the immutable lexical pack exporter**

```bash
git add src/learning/lexical_pack.py src/learning/lexical_exporter.py \
  tests/test_learning/test_lexical_pack.py tests/test_learning/test_lexical_exporter.py
git commit -m "feat(learning): export approved lexical backend packs"
```

### Task 7: Verify the complete lexical vertical slice and document operations

**Files:**
- Modify: `docs/learning-graph-operations.md:1-54`
- Modify: `tests/test_learning/conftest.py:1-300`
- Create: `tests/test_learning/test_lexical_vertical_slice.py`

- [ ] **Step 1: Write an end-to-end failing test**

Add the following fixture to `tests/test_learning/conftest.py`. It uses the
legacy schema created in Task 3 and produces exactly 30 valid senses plus one
quarantinable candidate.

```python
@pytest.fixture
def reviewed_lexical_sqlite(legacy_sqlite: Path) -> Path:
    connection = sqlite3.connect(legacy_sqlite)
    connection.execute("DELETE FROM word_sentences")
    connection.execute("DELETE FROM definitions")
    connection.execute("DELETE FROM sentences")
    connection.execute("DELETE FROM words")
    for index in range(30):
        suffix = chr(ord("a") + index // 26) + chr(ord("a") + index % 26)
        lemma = f"lex{suffix}"
        word_id = index + 1
        sentence_id = 1000 + word_id
        connection.execute(
            "INSERT INTO words VALUES (?, ?, 'noun', '/lɛks/', '/lɛks/', ?, 'A1', 'kaikki')",
            [word_id, lemma, 100 + index],
        )
        connection.execute(
            "INSERT INTO definitions VALUES (?, ?, ?, ?, NULL, 'kaikki')",
            [word_id, word_id, f"definition of {lemma}", f"nghĩa của {lemma}"],
        )
        connection.execute(
            "INSERT INTO sentences VALUES (?, ?, ?, NULL, NULL, NULL, 'tatoeba')",
            [sentence_id, f"Use {lemma} today.", f"Hãy dùng {lemma} hôm nay."],
        )
        connection.execute(
            "INSERT INTO word_sentences VALUES (?, ?)", [word_id, sentence_id]
        )
    connection.execute(
        "INSERT INTO words VALUES (99, 'badword', 'noun', '/bæd/', '/bæd/', 200, 'A1', 'kaikki')"
    )
    connection.execute(
        "INSERT INTO definitions VALUES (99, 99, 'broken definition', '[VI] broken definition', NULL, 'kaikki')"
    )
    connection.execute(
        "INSERT INTO sentences VALUES (1099, 'Use badword today.', 'Hãy dùng badword hôm nay.', NULL, NULL, NULL, 'tatoeba')"
    )
    connection.execute("INSERT INTO word_sentences VALUES (99, 1099)")
    connection.commit()
    connection.close()
    return legacy_sqlite
```

The end-to-end test registers the source snapshot, imports it, audits
candidates, approves all 30 validated senses, composes a pack, and opens its
SQLite output. It also proves that the `[VI]` candidate is absent.

```python
def test_lexical_reference_reaches_offline_pack_only_after_quality_review(tmp_path, reviewed_lexical_sqlite):
    graph_path = tmp_path / "graph.duckdb"
    store = LearningGraphStore(graph_path)
    store.initialize()
    catalog = SourceCatalog(store)
    checksum = hashlib.sha256(reviewed_lexical_sqlite.read_bytes()).hexdigest()
    catalog.register_source(
        SourceAssetInput(
            asset_id="legacy-sqlite",
            title="Legacy SQLite fixture",
            locator="https://example.test/legacy.sqlite",
            asset_version="2026-08-17",
            sha256=checksum,
            license_id="LicenseRef-Test",
            license_url="https://example.test/license",
            attribution="VocabCraft test fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    snapshot_id = catalog.record_source_snapshot(
        "legacy-sqlite", reviewed_lexical_sqlite, "2026-08-17T00:00:00+00:00"
    )
    SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        reviewed_lexical_sqlite, snapshot_id, "test-run"
    )
    audit = LexicalAuditService(store).audit(snapshot_id)
    repository = ContentRepository(store)
    candidate_ids = [
        row[0]
        for row in store.connection().execute(
            "SELECT candidate_id FROM content_candidates WHERE state = 'validated' ORDER BY candidate_id"
        ).fetchall()
    ]
    assert len(candidate_ids) == 30
    for candidate_id in candidate_ids:
        repository.review_candidate(str(candidate_id), "approved", "editor-1", "Reviewed fixture")

    pack = LexicalPackComposer(repository).compose(audit.validation_run_id, "lexical-a1", "0.1.0")
    result = LexicalPackExporter().export(pack, tmp_path / "lexical-a1")
    connection = sqlite3.connect(result.sqlite_path)
    assert connection.execute("SELECT count(*) FROM senses").fetchone() == (30,)
    assert connection.execute("SELECT count(*) FROM senses WHERE lemma = 'badword'").fetchone() == (0,)
    connection.close()
```

- [ ] **Step 2: Run the end-to-end test and confirm failure**

Run: `./.venv/bin/pytest tests/test_learning/test_lexical_vertical_slice.py -v`

Expected: FAIL until Tasks 1-6 are complete.

- [ ] **Step 3: Document the exact operator sequence and complete the test**

Replace the old single `snapshot-reference` example in
`docs/learning-graph-operations.md` with these commands, using a unique output
directory for every published version:

```bash
python main.py curriculum register-source --manifest data/manifests/legacy-sqlite.yaml
SOURCE_SNAPSHOT_ID="$(python main.py curriculum snapshot-source --asset-id legacy-sqlite --local-path data/output/english_dataset.db --retrieved-at 2026-08-17T00:00:00+00:00)"
python main.py curriculum snapshot-lexical-reference --reference-db data/output/english_dataset.db --snapshot-id "$SOURCE_SNAPSHOT_ID" --import-run-id 2026-08-17-lexical-v1
VALIDATION_RUN_ID="$(python main.py curriculum audit-lexical --snapshot-id "$SOURCE_SNAPSHOT_ID")"
python main.py curriculum report-lexical --validation-run-id "$VALIDATION_RUN_ID" --output-path data/output/reports/lexical-v1.json
python main.py curriculum review-candidate --candidate-id "$REVIEWED_CANDIDATE_ID" --decision approved --reviewer-id editor-1 --rationale "Reviewed against source and bilingual example"
python main.py curriculum compose-lexical --validation-run-id "$VALIDATION_RUN_ID" --pack-id lexical-a1 --version 0.1.0 --cefr-level A1 --output-dir data/output/curated/lexical-a1-0.1.0
```

Document that an editor must run `review-candidate` for every candidate selected
for publication after inspecting `lexical-v1.json`; `REVIEWED_CANDIDATE_ID` is
the UUID copied from that reviewed report row. `compose-lexical` fails when
no reviewed candidate exists or any source contributes fewer than 30 individually
approved senses in the selected CEFR band. The release checks are: no failed gates in the exported pack,
SQLite integrity/foreign keys pass, manifest hashes match, and at least 30
individually approved senses exist for every source in the pack.

- [ ] **Step 4: Run the focused and full verification suites**

Run:

```bash
./.venv/bin/pytest tests/test_learning/ -v
make test
ruff check src tests
black --check src tests
```

Expected: every command exits 0. Record the exact pass counts and formatter/lint
output in the implementation handoff.

- [ ] **Step 5: Commit tests and operating guide**

```bash
git add docs/learning-graph-operations.md tests/test_learning/conftest.py \
  tests/test_learning/test_lexical_vertical_slice.py
git commit -m "docs(learning): document audited lexical pack workflow"
```

## Final acceptance checklist

- [ ] `english_dataset.db` remains byte-identical before and after lexical import.
- [ ] Every raw lexical bundle is tied to an approved, checksummed source snapshot.
- [ ] An invalid candidate is quarantined with persisted gate codes; it cannot be approved or exported.
- [ ] An approved sense has an English definition, non-placeholder Vietnamese meaning, IPA evidence, and bilingual example.
- [ ] The exported pack contains no unapproved candidate and does not overwrite an existing publish directory.
- [ ] The pack manifest, SQLite integrity check, foreign-key check, and file checksums pass.
- [ ] Vocabulary lookup by `(lemma, pos)` uses the published SQLite index and makes no network request.

# Ingest Speedup — DuckDB-Native Kaikki Ingestion

**Date:** 2026-08-12
**Status:** Approved
**Sub-project:** 1 of 4 (pipeline improvement decomposition)
**Target:** Full Stage 1 (Kaikki + corpora) < 5 minutes

---

## 1. Executive Summary

The current Stage 1 Kaikki ingestion streams the 3.18GB dump through the Python `KaikkiSinglePassParser` at ~10K words/min, taking ~2 hours. The DuckDB-native JSONL read benchmark is 5.8s for the same file. This spec replaces the hot path with pure DuckDB SQL ingestion — native `read_json` into a landing table, then vectorized `INSERT INTO ... SELECT` with `UNNEST` for classification — while keeping `KaikkiSinglePassParser` as a fallback and validation oracle.

**Success criteria:**
- Kaikki ingest (words, definitions, phrases, relations, topics) completes in < 3 minutes
- Full Stage 1 (Kaikki + Tatoeba + OpenSubtitles + EnViCorpora) completes in < 5 minutes
- SQL path output is equivalent to Python parser output (verified by validation gate on sample)
- All existing pipeline tests continue to pass (152 passing)

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    STAGE 1 — FAST INGEST PATH                       │
│                                                                    │
│  kaikki JSONL (3.18GB, ~1.15M entries)                             │
│       │                                                            │
│       ▼                                                            │
│  [1] DuckDB read_json (native reader, controlled columns)          │
│       → raw_kaikki landing table (5.8s benchmark)                  │
│       │                                                            │
│       ▼                                                            │
│  [2] SQL classification (vectorized INSERT...SELECT, UNNEST)       │
│       ├─ raw_words      (single-word lemmas)                       │
│       ├─ raw_definitions(senses → glosses + examples)              │
│       ├─ raw_phrases    (multiword, pos in allowed set)            │
│       ├─ raw_relations  (syn/ant/hyper/hypo, sense+top-level)      │
│       └─ raw_topics     (sense-level topics)                       │
│       │                                                            │
│       ▼                                                            │
│  [3] Validation gate (SAMPLE mode): diff SQL path vs Python parser │
│       │  pass → proceed        fail → log + fall back to Python    │
│       ▼                                                            │
│  [4] Corpora ingest (unchanged, already fast via ParallelCorpus)   │
│                                                                    │
│  Target: Kaikki ~1-3 min + corpora ~1 min → Stage 1 < 5 min        │
└────────────────────────────────────────────────────────────────────┘
```

### New module

`src/ingestion/kaikki_sql.py` — owns the fast path:

- `ingest_kaikki_sql(conn, jsonl_path) -> IngestStats` — read + classify + insert, returns row counts per table
- `validate_sql_vs_python(conn, jsonl_path, sample_lines=50_000) -> ValidationResult` — the parity gate
- `_read_into_landing(conn, jsonl_path)` — native `read_json` into `raw_kaikki`
- `_classify_words/_definitions/_phrases/_relations/_topics(conn)` — vectorized INSERT...SELECT per table
- `drop_landing(conn)` — removes `raw_kaikki` after Stage 1

`src/stages/stage_1_ingest.py` calls the fast path:

```
if validate_sql_vs_python(...).passed:
    ingest_kaikki_sql(...)
else:
    KaikkiSinglePassParser(...)   # fallback, correct but slow
```

`KaikkiSinglePassParser` is untouched — remains the oracle and fallback.

---

## 3. Landing Table

`raw_kaikki` — one row per JSONL entry, nested structures kept as `JSON` type (read_json_auto guesses wrong on Kaikki's varying shapes, so explicit column typing is required):

```sql
CREATE TABLE raw_kaikki (
    word VARCHAR,
    pos VARCHAR,
    sounds JSON,
    senses JSON,
    translations JSON,
    synonyms JSON,
    antonyms JSON,
    hypernyms JSON,
    hyponyms JSON
);
```

Sense-level relation arrays (`sense.synonyms` etc.) are not separate landing columns — they are extracted inline via `json_extract` during relation classification (see 4.4).

Read options: `read_json(path, format='newline_delimited', ignore_errors=true, columns={...})`. Skipped (corrupt) lines are counted; the count must approximate the Python parser's `JSONDecodeError` count.

`raw_kaikki` is dropped at the end of Stage 1 (~3GB of raw JSON would bloat `staging.duckdb`).

---

## 4. SQL Classification Rules

All classification runs as vectorized `INSERT INTO ... SELECT` from `raw_kaikki`, using `json_extract` + `UNNEST`. Each rule mirrors `KaikkiSinglePassParser` exactly.

### 4.1 raw_words
```sql
INSERT INTO raw_words (lemma, pos, ipa_uk, ipa_us)
SELECT word, pos,
       (SELECT min(s.ipa) FROM UNNEST(sounds) s WHERE list_contains(s.tags, 'UK') OR list_contains(s.tags, 'British')) AS ipa_uk,
       (SELECT min(s.ipa) FROM UNNEST(sounds) s WHERE list_contains(s.tags, 'US') OR list_contains(s.tags, 'American')) AS ipa_us
FROM raw_kaikki
WHERE position(' ' in word) = 0;
```

IPA fallback rule (no tagged sound): first sound's IPA → both ipa_uk and ipa_us, expressed as a second query or a `COALESCE` wrapping the lookup results.
Word/phrase classification happens **before** any other extraction — phrases get no relations/definitions/words entries.

### 4.2 raw_definitions

`UNNEST(senses)` per word:

- gloss: first non-empty gloss; `glosses` preferred, fallback `raw_glosses` when empty
- example: first example, dict `.text` or bare string
- source: `Kaikki/Wiktionary`

### 4.3 raw_phrases

- `position(' ' in word) > 0` AND `pos` ∈ {idiom, phrasal verb, proverb, phrase}
- ≤ 6 words unless `pos = proverb`
- matches regex `^[a-zA-Z '.-]+$`
- skipped if no definition (first non-empty gloss)

### 4.4 raw_relations

UNION of top-level + sense-level synonym/antonym/hypernym/hyponym arrays:

- skip targets equal to self, length 1, or not matching the clean regex
- dedupe on `(relation_type, target_text)`
- cap 25 relations per type per word, traversal order preserved via `row_number() OVER (PARTITION BY word, relation_type ORDER BY ...)` keeping `row_number <= 25`

### 4.5 raw_topics

`UNNEST(senses.topics)`, dedupe case-insensitively on `(word, topic)`.

### 4.6 IPA extraction

- first sound with UK/British tag → ipa_uk
- first sound with US/American tag → ipa_us
- if neither tagged, first sound → both ipa_uk and ipa_us

### 4.7 VI translations

`translations` where `code = 'vi'` or `lang = 'Vietnamese'`, joined with `", "` — stored as nullable column (backfill stage handles the rest).

### Equivalence strategy

Caps/dedup/ordering are handled with `row_number()` window functions over unnested sets — deterministic and vectorized, no per-row Python.

---

## 5. Validation Gate

Safety net before committing to the fast path on the full dump:

1. Take first N lines (default 50K) of the Kaikki dump
2. Run the SQL fast path against an **in-memory DuckDB connection** (same landing + classification queries, `:memory:` database) so real staging tables are never polluted by sample runs
3. Run the Python parser over the same N lines, in memory
4. Diff each table on row counts and content sets (same keys/values)
5. `PASS` → proceed to full SQL ingest against the real staging DuckDB
6. `FAIL` → log diffs, fall back to `KaikkiSinglePassParser` for the full run (correct but slow), surface warning in final report

Sample mode costs ~30-60s — amortized against a 2-hour run, worth it.

---

## 6. Error Handling

| Scenario | Behavior |
|----------|----------|
| Corrupt JSONL line | `ignore_errors=true` skips; skip count logged and asserted equal to the Python parser's `JSONDecodeError` count (mismatch → gate fails, fall back) |
| Missing `senses`/`translations`/`sounds` | `json_extract` returns NULL → matches Python `item.get()` defaults |
| Empty `word` | Filtered in SQL (`WHERE word IS NOT NULL AND word != ''`) |
| Validation gate fails | Fall back to Python parser, log diffs, warn in report |
| Mid-way failure | DAG checkpoint machinery handles resume; stage re-runs from scratch, idempotent via `INSERT OR IGNORE` |

---

## 7. Testing

1. **Unit tests** (`tests/test_kaikki_sql.py`): SQL classification against small handcrafted JSONL fixtures — same fixture data as `test_kaikki_single_pass.py`, asserting identical row sets per table
2. **Parity test**: same fixture → both paths → assert equal (the gate's engine, reusable)
3. **Integration**: `test_pipeline_integration.py` extended — Stage 1 with the SQL path on a small dump, assert staging tables populated + timing logged
4. **Benchmark test** (marked, not run by default): full Kaikki dump timing — assert < 5 min or log + warn

---

## 8. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Kaikki ingest | ~2 hours | < 3 min |
| Full Stage 1 | ~2+ hours | < 5 min |
| SQL/Python parity | n/a | 100% on sample gate |
| Test suite | 152 passing | 152 passing + new tests |
| `raw_kaikki` footprint | n/a | dropped after Stage 1 |

---

## 9. Out of Scope (future sub-projects)

- Fix legacy test breakage (25 tests referencing pre-redesign infrastructure)
- Data quality & completeness checks (dedupe, missing relations, quality gates)
- Pipeline UX & ops (logging, metrics, checkpoint visibility)

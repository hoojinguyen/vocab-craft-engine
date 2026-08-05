# Sentences Coverage — Phase A Design

**Date:** 2026-08-05
**Status:** Approved for implementation planning

## 1. Goal

Expand the example-sentence corpus so that **≥ 95% of the 3,000 core pack words have at least one English–Vietnamese example sentence** (up from ~90.4% today, where 288 words are quarantined for missing `example_en`). The corpus also feeds Phase B (collocation mining) and Phase C (dialogue trees) in later cycles.

The expansion is 100% from **free, human-translated sources** — no MT translation for the bulk volume. Source is tagged per sentence so consumers (and the app) can prefer cleaner sources.

## 2. Findings Driving This Spec

| Metric | Today |
|---|---|
| `sentences` rows | 18,702 (source: Tatoeba 18,696 + DialogueTree 6) |
| `word_sentence_map` rows | 50,971 |
| Distinct words with ≥1 sentence | 5,862 / 1,032,521 (0.6%) |
| Core pack words with example | ~2,712 / 3,000 (90.4%) |
| Core pack quarantined (no example anywhere) | 285 |
| Raw dump English sentences (Tatoeba, `sentences.csv`) | 2,029,850 |
| Raw dump Vietnamese sentences | 32,398 — **Tatoeba en↔vi is nearly exhausted** (~14K pairs unused) |

The current Tatoeba-only pipeline has a hard ceiling: only ~32K Vietnamese sentences exist in the dump, and ~18.7K are already ingested. A second human-translated en↔vi source is required to close the gap.

## 3. Data Sources (free, human-translated)

All sources verified reachable on 2026-08-05.

1. **OpenSubtitles en↔vi (OPUS v2024)** — ~3.5M aligned subtitle pairs, human-translated. Direct download, **verified HTTP 200** (951MB):
   `https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/en-vi.txt.zip`
   Moses format (line-aligned `en-vi.txt.en` + `en-vi.txt.vi`). Primary volume source. Tag `source='OpenSubtitles'`.
   (Alternative, unverified: `sinhngn/English-Vietnamese-parallel-corpus-context` — repo is 404 as of 2026-08-05, do not use.)
2. **EnViCorpora** — `thanhleha-kit/EnViCorpora` (GitHub), files vendored via raw URLs (verified sizes below):
   - `ted-like/data.en` (23MB) + `data.vi` (31MB) → ~546K pairs, educational talks. Tag `source='TED-EnVi'`.
   - `basic/data.en` (283KB) + `data.vi` (399KB) → 8.8K conversational. Tag `source='Basic-EnVi'`.
   - Its `openSub/` folder only contains a dead Google Drive link (2020) — do not use; the OPUS source (1) covers subtitles.
3. **Tatoeba API** (fallback, last resort): `api.tatoeba.org` — on-demand lookup of sentences containing a specific core word with existing Vietnamese translation. Used only for the remaining core words not covered by sources 1–2, and only for words whose `example_en` is still missing. Tag `source='Tatoeba'`. Rate-limited to 1 req/sec.

Source preference for core-word example selection (after Phase A): **TED-EnVi > Basic-EnVi > Tatoeba (new) > OpenSubtitles** — cleaner domains rank above subtitle noise; existing Tatoeba DB rows keep their rank.

## 4. Pipeline

### 4.1 Download (`scripts/`)
- Extend `scripts/download_raw_data.py` with resumable download + integrity check for:
  - **OPUS OpenSubtitles en-vi** moses zip (951MB, URL in Section 3): stream-unzip (no full 951MB in-memory), verify zip CRC over the two extracted files, archive to `data/raw/opensubtitles_envi/`.
  - **EnViCorpora** `ted-like` + `basic` (`data.en`/`data.vi` pairs, small) → `data/raw/envicorpora/`.
- Downloaded once, vendored; downloads must be resumable (partial-file tolerance) with checksum verification. Space check: warn if < 4GB free before the 951MB download.

### 4.2 Parse (`src/ingestion/`)
- **Extend `OpusParser`** (currently expects `en \t vi` lines, 2–12 words only) into a general `ParallelCorpusParser`-style reader:
  - Accept `en`/`vi` side-by-side files (Moses format) or tab-separated lines.
  - Drop the hard 2–12 word limit at parse time; move filtering to an explicit filter step (4.3) so filter rules are unit-testable in isolation.
  - Yield `{text_en, text_vi, source}`; dedupe on normalized `(text_en, text_vi)` pairs (subtitle corpora repeat heavily across movies).

### 4.3 Filtering (noise rules — the core difficulty)
Per pair, keep only if ALL of:
1. `len(text_en.split())` between 2 and 30 words (reuse Tatoeba rule).
2. `text_en` starts with an alphanumeric char or `"`/`'` (reuse `TatoebaParser._is_clean_sentence`).
3. `text_vi` non-empty; `text_vi != text_en` case/punctuation-insensitive (reuse `Translator._is_passthrough` logic — subtitle files contain untranslated English lines).
4. Reject subtitle noise: lines matching `♪`, `[bracketed]`, `(parenthetical)`, `*asterisked*`, ALL-CAPS name labels, or containing phone-number/digit-heavy patterns.
5. Drop pairs already present in the DB (`sentences.text_en` exact match) — ingestion is idempotent on re-run.

No CEFR/lemma filtering at ingestion time; linking to words happens in 4.4.

### 4.4 Linking (`word_sentence_map` rebuild)
- Reuse the existing link step from `main.py` (Step 4B): lemmatize each `text_en` via the existing lemmatizer, match against `words.lemma`.
- Incremental: only link newly inserted sentences (track `MAX(sentences.id)` checkpoint), so full re-linking of 1M words is never needed.
- A core word's example picks the **highest-preference source available** (Section 3 preference order), then CEFR-fit (existing rule: sentence CEFR ≤ word CEFR + 1).

### 4.5 Core pack rebuild
- Re-run `--build-core-pack` (existing step, now with the expanded sentence pool). Quarantined words whose `example_en` gate now passes are **automatically un-quarantined and added to the pack** on the next build (no manual intervention; the pack builder re-evaluates all 3,000 words each run).
- New sentences get CEFR grading via existing `CefrGrader` (rank → threshold), and audio only if/when the production audio run happens (audio generation for new sentences is **out of scope** — sentence audio reuses existing sentence audio files; new rows get `audio_path` reserved but generation deferred, matching the existing audio_status model).

## 5. Success Gates

1. **≥ 95% of core words have ≥1 example sentence** (en + vi) — measured in `quality_report.md` after pack rebuild. Expected outcome: quarantine for missing examples drops from 288 toward < 150.
2. **Ingestion idempotent:** re-running the ingest step inserts 0 new rows.
3. **No invariant violations:** existing `build_report_invariants` (every packed word has topic/vi/audio) stays green.
4. **Corpus growth:** `sentences` rows increase from 18,702 to a floor of ~100K after filtering (target volume; exact count depends on filter yield).
5. **Regression:** full test suite stays green; existing tests that hard-code sentence counts are updated deliberately (they are fixtures, not DB-dependent).

## 6. Error Handling & Robustness

- **Download:** resumable, checksummed; a failed download aborts the step with a clear message — never leaves a corrupt partial archive as "complete".
- **Parse/filter:** malformed lines are skipped with a counter logged (not fatal); per-file progress logged.
- **Checkpoint:** ingest step records `last_sentence_id`; re-run skips already-ingested content (idempotent by design, no fragile state).
- **Rate limits:** Tatoeba API fallback throttled (1 req/sec), only used for the residual core words; a failure there leaves the word quarantined (existing behaviour) — never blocks the run.
- **Disk:** the raw OpenSubtitles archive is 951MB; verify available space before download, warn if < 4GB free.

## 7. Testing

- **Unit — parser:** Moses/TSV parsing, dedupe on normalized pairs, idempotency.
- **Unit — filters:** each noise rule (brackets, passthrough vi, digit-heavy, ALL-CAPS labels, length bounds) has its own test with representative fixtures.
- **Unit — linking:** incremental linking only touches rows > checkpoint; lemmatization match against `words.lemma`.
- **Integration:** ingest sample corpus file → assert row counts, `source` tags, dedupe, no DB duplicates, `word_sentence_map` linked.
- **End-to-end:** rebuild core pack from the small-DB fixture (existing test pattern) with the new sentence pool → assert example coverage improves and `build_report_invariants` stays green.
- **Gate check:** a test asserts the ≥95% coverage computation matches `quality_report.md` output format.

## 8. Out of Scope (Deferred)

- **Phase B** — collocation/phrase mining from the expanded corpus (separate spec).
- **Phase C** — dialogue-tree generation from subtitle context windows (separate spec).
- Sentence audio generation for new rows (deferred to the production audio run).
- LLM-generated example sentences (cost decision deferred; not needed if gates are met with free sources).
- Any changes to `words`, `definitions`, `collocations`, `phrases` content beyond `sentences` + `word_sentence_map`.

# Core 3000 Word Pack — Design

**Date:** 2026-08-04
**Status:** Approved for implementation planning

## 1. Goal

Build a curated, self-owned **core vocabulary pack of ~3,000 most common English words** at the highest achievable quality, packaged for an offline-first English learning app targeted at **Vietnamese learners**. The pack is generated 100% from local heuristics and vendored data files — no runtime or build-time API dependency.

Primary app features served: **vocabulary & flashcards** and **listening & conversation**.

## 2. Provenance & "Commonness" Evidence

The 3,000 words are selected and *validated* by three independent local sources:

1. **SUBTLEX-US frequency rank** (`data/raw/SUBTLEX_US.csv`, 50K words) — the selection signal. Rank ≤ ~3500 candidate window.
2. **NGSL (New General Service List)** — ~2,800 words covering ~92% of general English text, freely licensed. Vendored once into `data/raw/` (via `scripts/download_raw_data.py`). **Gate: ≥85% overlap** between our 3,000 pack and NGSL.
3. **Tatoeba corpus coverage** — measure % of tokens in the existing 18.7K-sentence corpus covered by the pack. **Gate: ≥90%.**

If either gate fails, the candidate window automatically widens (rank ≤ 4000) and selection re-runs; the widest window is 5000.

## 3. Selection Pipeline (Step 5A — Select Core)

Inputs: SUBTLEX_US.csv, `words` table (from Kaikki), `definitions` table.

Per candidate word (rank order):
1. Normalize: lowercase, expand contractions (`don` → `do`, `i` → `I`), strip punctuation forms.
2. Join with Kaikki `words` table by lemma — keep only words that exist as a Kaikki lemma (need at least one definition).
3. Filter out noise POS: `name`, `prefix`, `suffix`, `symbol`, `numeral`, `punctuation`, `particle` (single-letter forms).
4. Sort by SUBTLEX rank; take exactly 3,000.
5. Run NGSL overlap + Tatoeba coverage gates (Section 2). On failure, widen window and re-run.

## 4. Quality Pass (Step 5B — Per-Word Enrichment)

For each of the 3,000 words, produce the following. Any missing field fails that word's gate.

1. **CEFR (grade-first, correct):** map SUBTLEX frequency rank to thresholds: A1 = rank ≤ 500, A2 = 501–1500, B1 = 1501–3500, B2 = 3501–7000, C1 = 7001–15000, C2 > 15000. Never leaves a word at the default `C2` fallback. (Overrides the existing grader's "unknown → C2" behaviour for the pack.)
2. **definition_en:** first sense ordered by Kaikki (most common sense first), human-readable.
3. **definition_vi:** existing validated translation cache first → `deep-translator` fallback → `VietnameseValidator.is_vietnamese` + passthrough rejection (reuse current `Translator._is_passthrough`). Generic/ambiguous one-word glosses that fail validation are a gate failure (quarantined), never written empty.
4. **example_en + example_vi:** pick from Tatoeba via `word_sentence_map`, filtered to sentences whose CEFR ≤ word CEFR + 1 (comprehensible input). Fallback: Kaikki `definitions.example`. `example_vi` translated + validated. Each core word needs ≥1 example in both languages.
5. **IPA:** UK + US from `words` table.
6. **Topic:** ≥1 theme from the curated 18-theme taxonomy (Section 5). Pack must cover ≥15/18 themes; if a theme is under-represented, backfill candidates come from the ranked candidate window.
7. **Audio:** word-level audio std + fast (1.0x/1.2x) via existing Edge-TTS generator; relative paths `audio/std/w_{id}.mp3` / `audio/fast/w_{id}.mp3`. Sentence audio copies existing files.

**Quality gates (all-or-nothing):** a word passes only if ALL of: definition_vi valid, example_en + example_vi present, CEFR non-default, IPA present, ≥1 topic, both audio files generated. Failures go to a `quarantine` table with the failing gate listed. Pack is releasable only when pass rate ≥ 97% (`quarantine` < 90 of 3000).

## 5. Topic Coverage Fix

Findings driving this section:

- `word_topics` covers only 142,579 / 1,032,521 words (13.8%). Most common words have no Wiktionary topic tag.
- `THEME_MAP` (~120 keys) leaks ~500 raw Kaikki topics into the DB unmerged (e.g. `Organic Chemistry`, `Microbiology`, `Mineralogy`, `Pathology` appear as-is instead of collapsing into the curated themes).

Changes:

1. **Expand `THEME_MAP`** to ~600+ keyword entries, sourced by harvesting the actual distinct raw topics present in `word_topics` and mapping each one to a curated theme. Stored as config file `config/theme_map.yaml` (source of truth), loaded by `TopicMapper`.
2. **One-time DB cleanup** of the parent DB: rewrite `word_topics` through the new map so all 500+ raw topics collapse into the 18 curated themes. Benefits the full 1M-word DB, not just the pack.
3. **Fallback theme `General & Everyday`** assigned to any core word with no domain topic. Gate guarantees 100% of pack words have ≥1 theme.
4. Coverage metric: ≥15/18 themes represented in the pack; `quality_report.md` lists per-theme word counts.

## 6. Export (Step 5C — core_3000.db)

App-focused schema, composite indexes, WAL mode:

```
words            id, lemma, pos, cefr_level, frequency_rank, ipa_uk, ipa_us,
                 audio_std, audio_fast, audio_status
word_topics      word_id ↔ topic (18 themes)
definitions      word_id, definition_en, definition_vi, example_en, example_vi,
                 example_vi_source
sentences        id, text_en, text_vi, cefr_level, audio_path, source
word_sentences   word_id ↔ sentence_id  (3–5 sample sentences per word, CEFR-matched)
collocations     phrase, meaning_vi, pos_pattern, cefr_level, root_word_id
phrases          idioms/proverbs: phrase, definition_en, definition_vi,
                 cefr_level, audio_std, audio_fast  (high-frequency only)
quarantine       word_id, lemma, failed_gate(s)
```

- Relative audio paths (portable bundle).
- Secondary output: `quality_report.md` (per-gate metrics, per-theme counts, NGSL overlap %, Tatoeba coverage %).
- Packed via SQLiteExporter (indexes + WAL, as the existing mobile packaging).

## 7. Error Handling & Robustness

- **Checkpoint:** `data/processed/core_pack_checkpoint.json` — re-runs resume (skip translated/audio-done words); idempotent.
- **Failure isolation:** a few word-level failures (translation, audio) never abort the pack — logged + quarantined; the run completes.
- **MT budget:** reuse `--vi-budget` mechanism for pack translations (definitions + example_vi). Budget consumption is tracked per word so re-runs are deterministic.
- **Gate shortage policy:** currently only quarantine; automatic replacement from candidate window is out of scope (deferred).

## 8. Testing

- **Unit:** candidate selection (contraction expansion, POS filtering, rank cut); CEFR rank→threshold mapping; new theme map (raw→theme collapse, e.g. `Organic Chemistry` → Science & Mathematics); gate logic; quarantine behaviour; checkpoint resume.
- **Validation gates (Section 2):** NGSL overlap ≥85%, Tatoeba coverage ≥90% — unit tests on sample data; the full run prints actual metrics to `quality_report.md`.
- **Integration:** build pack from sample DB → open `core_3000.db` → assert every gate passes, every word has a topic, audio paths are relative, indexes/schema exist, quarantine < 97% threshold.
- **Regression:** existing suite stays green (pack builder is additive; parent ETL untouched).

## 9. Out of Scope (Deferred)

- LLM-assisted QC and any human-in-the-loop review tooling.
- Automatic replacement of quarantined words from the candidate window.
- Full listening/conversation pack (dialogues, scenario drills) for the core words.
- Packed DB signing/versioning inside the app bundle.
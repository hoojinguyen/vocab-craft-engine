# Design Spec: Pipeline Performance Optimization & Hybrid Vietnamese Translation Engine

**Date:** 2026-08-10  
**Status:** Approved  
**Topic:** Pipeline Performance Optimization (Step 4G & 4I) & Hybrid Vietnamese Translation Engine  

---

## 1. Executive Summary

During execution of `make run` recorded in [`log`](file:///Users/hoojinguyen/My-Workspace/Tools/vocab-craft-engine/log), the ETL & NLP enrichment pipeline completed in **6,638.97 seconds (~1h 50m)**. Analysis revealed two major bottlenecks and data coverage gaps:
1. **Step 4G (Multi-Word Expressions):** Took ~94 minutes for 4,415 phrases due to single-threaded HTTP translation calls during Kaikki parsing (~55 mins) and un-indexed in-memory Python sentence matching (~24 mins).
2. **Step 4I (Vietnamese Translation Backfill):** Took 14 minutes but translated only 814 definitions (~0.05% coverage out of 1.44 million definitions) due to `VI_TRANSLATION_BUDGET=1000` cap and sequential HTTP requests.

This specification details the architecture and component redesign for **Step 4G** and **Step 4I** using a **High-Performance Async Pipeline + Hybrid Offline Translation Engine**. Target outcomes:
- **Step 4G execution time:** Reduced from ~94 minutes to **< 2 minutes**.
- **Step 4I translation speed:** Accelerated by **20x–30x** via multi-threaded async workers and offline gloss extraction, achieving **100% Vietnamese coverage for Core 3000 & Top 10,000 words**.
- **Zero broken passthrough:** Strict validation using `VietnameseTextValidator`.

---

## 2. Architecture & Component Overview

```
                  ┌──────────────────────────────────────────────────┐
                  │           Kaikki, Tatoeba, OpenSubtitles         │
                  └─────────────────────────┬────────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────────────────┐
                    │      Step 4G: Phrase Engine (Optimized)      │
                    │  - Offline Phrase Gloss Lookup (Instant 0ms) │
                    │  - SQL-Indexed Sentence Matching (~1s/batch) │
                    └───────────────────────┬──────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────────────────┐
                    │  Step 4I: Hybrid Vietnamese Translation      │
                    │  ┌────────────────────────────────────────┐  │
                    │  │ Phase 1: Local Offline Gloss Extractor │  │
                    │  │   (Kaikki/Tatoeba/Subtitles Glosses)   │  │
                    │  └───────────────────┬────────────────────┘  │
                    │                      │ (If unmapped/NULL)    │
                    │                      ▼                       │
                    │  ┌────────────────────────────────────────┐  │
                    │  │ Phase 2: Multi-Worker Async Translator │  │
                    │  │   (Tiered Priority: Core 3000 -> 10k)  │  │
                    │  └────────────────────────────────────────┘  │
                    └───────────────────────┬──────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────────────────┐
                    │ Step 5: Fast Packaging & Benchmark Validation│
                    └──────────────────────────────────────────────┘
```

### Components Introduced / Modified:
1. **`src/nlp/offline_gloss_extractor.py` (New):**
   Scans raw dataset dumps (Kaikki JSON Vietnamese glosses, Tatoeba aligned pairs, OpenSubtitles En-Vi pairs) to build an in-memory / SQLite-backed instant lookup map ($O(1)$) for Vietnamese glosses.
2. **`src/nlp/phrase_example_matcher.py` (Modified):**
   Replaces in-memory Python scanning of 975,000 sentences with indexed SQL candidate queries (`SQLPhraseExampleMatcher`), constraining candidate evaluation to indexed keyword matches per phrase.
3. **`src/nlp/translator.py` & `AsyncBatchTranslator` (Modified/New):**
   Upgrades `Translator` to support `concurrent.futures.ThreadPoolExecutor(max_workers=20)` with exponential backoff retries, sliding window rate-limiting, and hard per-request timeouts (5s).
4. **`main.py` (Modified):**
   Removes single-threaded online HTTP translation from `run_phrase_step` (Step 4G) and updates `run_vietnamese_step` (Step 4I) to execute Phase 1 (offline update) followed by Phase 2 (tiered priority async translation).

---

## 3. Detailed Component Designs

### 3.1. Step 4G: Multi-Word Expressions Optimization

#### A. Removal of Online HTTP Calls in Staging
- In `run_phrase_step()` (`main.py`): Replace `translator.translate_text(item["phrase"])` with `offline_gloss_extractor.get_translation(item["phrase"])`.
- If no offline translation exists, set `definition_vi = NULL`. Un-translated phrases will be staged instantly (55 mins -> < 5s) and delegated to Step 4I's batch translator.

#### B. SQL-Indexed Sentence Matching (`SQLPhraseExampleMatcher`)
- Instead of building a Python `_word_index` across 975,000 sentence objects in RAM:
  1. Extract key non-stopword stems for each phrase $P$.
  2. Query SQLite `sentences` table using SQL indexed text search for matching candidate sentences (`LIMIT 50` candidates per phrase).
  3. Apply boundary and inflection checks only on the 50 candidate sentences in Python, sorting by CEFR level (`LIMIT 5`).
  4. Execution time drops from 24 minutes to < 30 seconds.

### 3.2. Step 4I: Hybrid Vietnamese Translation Engine

#### A. Phase 1: Local Offline Gloss Extractor (`OfflineGlossExtractor`)
- Parses Kaikki raw dump for entries with `lang_code == "vi"`, mapping English lemmas and definitions to Vietnamese translations.
- Integrates existing Tatoeba and OpenSubtitles aligned sentence glosses.
- Executes batch SQL `UPDATE` statements for matching `NULL` rows in `definitions`, `collocations`, and `phrases`.
- Resolves 50%–70% of missing translations in seconds with 0ms network latency.

#### B. Phase 2: Tiered Priority Async Translator (`AsyncBatchTranslator`)
- Uses `concurrent.futures.ThreadPoolExecutor(max_workers=20)` for concurrent HTTP translation requests.
- **Tiered Priority Queue:**
  - **Priority 1:** Core 3000 words & Frequency Rank 1..10,000 (`CEFR A1, A2, B1, B2`).
  - **Priority 2:** High-frequency collocations and phrases.
  - **Priority 3:** Extended vocabulary glosses up to the allocated `vi_budget`.
- **Batch Cache Persistence:** Commits to SQLite and updates `translation_cache.json` after every 100 successful translations, maintaining 100% idempotency and auto-resume capability.

---

## 4. Error Handling & Resilience

1. **Rate Limit & Network Failures (HTTP 429/503):**
   - Each worker implements Exponential Backoff with Jitter (0.5s – 2.0s delay).
   - Hard request deadline of 5.0 seconds per translation call. If timed out or errored, returns `""` (`NULL` in DB) without halting the pipeline.
2. **Vietnamese Text Validation:**
   - Every candidate translation passes through `VietnameseTextValidator.is_vietnamese()`.
   - Passthrough strings (identical to English source) are converted to `NULL` to prevent corrupted data.
3. **Database Transaction Safety:**
   - Uses parameterized SQL `executemany` with explicit transaction commits per batch chunk.

---

## 5. Testing & Verification Plan

### 5.1. Unit & Integration Tests
- `tests/test_offline_gloss_extractor.py`: Verify offline mapping accuracy from Kaikki Vietnamese entries.
- `tests/test_async_translator.py`: Test thread-pool concurrency, timeout handling, and cache writing.
- `tests/test_phrase_matcher.py`: Test SQL candidate filtering accuracy and boundary checking.

### 5.2. Pipeline Benchmark Criteria
Run `make run` and verify against log benchmarks:
- **Step 4G total duration:** < 2 minutes (down from 94 minutes).
- **Step 4I translation speed:** > 25 translations per second.
- **Core 3000 Vietnamese coverage:** 100% of Core 3000 word definitions translated to valid Vietnamese.
- **Full Test Suite:** Run `make test` to ensure 100% pass rate.

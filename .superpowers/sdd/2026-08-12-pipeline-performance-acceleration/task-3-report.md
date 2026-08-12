# Task 3 Report: Multi-Core Parallel NLP Processor & CLI Flag

## Summary

Implemented `ParallelProcessor` in `src/nlp/parallel_processor.py` utilizing Python's `concurrent.futures.ProcessPoolExecutor` to distribute NLP workload (sentence lemmatization and grammar pattern extraction) across available CPU cores. Integrated `ParallelProcessor` into `main.py` along with the `--no-parallel` CLI flag, and created comprehensive unit tests in `tests/test_pipeline_performance.py`.

## Implementation Details

1. **`ParallelProcessor` Class (`src/nlp/parallel_processor.py`)**
   - Utilizes `ProcessPoolExecutor` with process initializer functions (`_init_lemmatizer_worker` and `_init_pattern_worker`) to instantiate spaCy instances (`Lemmatizer` and `GrammarPatternExtractor`) per worker process.
   - Provides `process_sentence_lemmatization(sentences, chunk_size)`:
     - Consumes sentence tuples `(id, text_en)` or dictionaries.
     - Splits input into balanced chunks across worker processes.
     - Returns list of dictionary entries: `{"sentence_id": s_id, "lemma": lemma, "text": text, "pos": pos}`.
   - Provides `process_pattern_extraction(sentences, chunk_size)`:
     - Consumes sentence tuples `(id, text_en, text_vi)` or dictionaries.
     - Runs `GrammarPatternExtractor` in parallel across worker processes.
     - Returns list of extracted pattern matches for database batch insertion.
   - Supports `disable_parallel=True` flag or single-worker fallback to execute sequentially on the main thread without process overhead.

2. **Integration into `main.py`**
   - Added `--no-parallel` argument to `parse_arguments()` allowing users to opt out of parallel processing when needed.
   - Updated `_link_sentences_incrementally(db_manager, checkpoint, args)` to process sentence lemmatization via `ParallelProcessor`.
   - Updated `run_pattern_step(db_mgr, args)` to extract grammar sentence patterns across sentences via `ParallelProcessor`.

3. **Testing & Verification**
   - Created `tests/test_pipeline_performance.py`:
     - `test_parallel_processor_lemmatization`: Tests parallel multi-process lemmatization output correctness and lemma extraction (`"fox"`, `"jump"`/`"jumps"`).
     - `test_parallel_processor_no_parallel_flag`: Tests sequential execution when `disable_parallel=True`.
   - Verified initial failure (`ModuleNotFoundError: No module named 'src.nlp.parallel_processor'`).
   - Verified tests pass after implementation.
   - Ran full project test suite: 197 passed in 54.79s (100% pass rate).

4. **Git Commit**
   - Commit `7dd7929`: `feat(nlp): add Multi-Core ParallelProcessor and --no-parallel CLI flag`

## Files Created & Modified

- [`src/nlp/parallel_processor.py`](file:///Users/hoojinguyen/My-Workspace/Tools/vocab-craft-engine/src/nlp/parallel_processor.py)
- [`main.py`](file:///Users/hoojinguyen/My-Workspace/Tools/vocab-craft-engine/main.py)
- [`tests/test_pipeline_performance.py`](file:///Users/hoojinguyen/My-Workspace/Tools/vocab-craft-engine/tests/test_pipeline_performance.py)

## Review Findings & Fixes

1. **Chunked Memory Streaming in `run_pattern_step` and `_link_sentences_incrementally`**:
   - Refactored `run_pattern_step` and `_link_sentences_incrementally` to stream sentences in chunks of 50,000 using `cursor.fetchmany(50000)` instead of loading all sentences into memory with `cursor.fetchall()`.

2. **Checkpoint Calculation Fix in `_link_sentences_incrementally`**:
   - Updated checkpoint tracking to compute `new_max` directly from the sentence IDs fetched from the database (`chunk_max = max(s[0] for s in sentences)`), ensuring sentences without lemmatized tokens (e.g., numbers/punctuation) still advance the checkpoint correctly.

3. **Verification**:
   - Re-ran `pytest tests/` and confirmed all 197 tests pass cleanly.

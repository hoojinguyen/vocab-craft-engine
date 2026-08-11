# Design Spec: Automatic Grammar Sentence Pattern Extractor

**Date:** 2026-08-11  
**Status:** Approved  
**Module:** `src/nlp/pattern_extractor.py`, `src/db/staging_db.py`, `main.py`, `src/export/sqlite_exporter.py`  

---

## 1. Executive Summary & Goals

The Grammar Sentence Pattern Extractor (`GrammarPatternExtractor`) automatically parses English corpus sentences (from Tatoeba/OPUS datasets) using SpaCy's `DependencyMatcher` and `Matcher` rule-based AST syntax matching. It identifies 60+ core English grammar patterns (e.g. `It is + Adj + to V`, `So... that`, `Would mind + V-ing`, `Not only... but also...`), tags them with CEFR difficulty levels (`A1` to `C2`), maps them N-N to corpus sentences, selects representative example sentences, and exports them into SQLite for mobile offline consumption with sub-1ms query response time.

---

## 2. Architecture & Component Design

### 2.1 Grammar Pattern Extractor (`src/nlp/pattern_extractor.py`)
Class `GrammarPatternExtractor` initializes a catalog of 60+ SpaCy dependency patterns categorized by CEFR levels.

#### Pattern Categories:
* **A1–A2:**
  - `it_is_adj_to_v`: *"It is easy to learn English"* (`it` + `be` + `ADJ` + `to` + `VERB`)
  - `too_adj_to_v`: *"He is too young to drive"* (`too` + `ADJ` + `to` + `VERB`)
  - `used_to_v`: *"I used to live in Paris"* (`used` + `to` + `VERB`)
  - `would_like_to_v`: *"I would like to order"* (`would` + `like` + `to` + `VERB`)
  - `there_is_are`: *"There are many reasons"* (`there` + `be` + `NOUN`)
* **B1–B2:**
  - `so_adj_that`: *"She was so tired that she slept"* (`so` + `ADJ` + `that` + clause)
  - `would_mind_ving`: *"Would you mind opening the door?"* (`would` + `mind` + `V-ing`)
  - `had_better_v`: *"You had better see a doctor"* (`had` + `better` + `VERB`)
  - `not_only_but_also`: *"Not only rich but also kind"* (`not only` + `but also`)
  - `passive_voice`: *"The house was built in 1990"* (`be` + `VERB` [VBN])
  - `conditional_type_1_2_3`: Conditional sentence structures (*If I were you...*, *If it rains...*)
* **C1–C2:**
  - `inversion_negative`: *"Hardly had I arrived when..."* (Negative adverbial inversion)
  - `cleft_sentence`: *"It was John who broke the window"* (Cleft sentence)

#### Core Interface:
```python
class GrammarPatternExtractor:
    def __init__(self, nlp_instance=None):
        ...
        
    def extract_patterns(self, text: str) -> List[Dict[str, Any]]:
        """
        Parses text and returns matched grammar pattern records.
        Return payload:
        [
            {
                "pattern_name": "it_is_adj_to_v",
                "cefr_level": "A2",
                "structure_json": '{"pattern": "It + be + Adj + to + Verb"}',
                "matched_tokens_json": '[{"text": "It", "pos": "PRON"}, ...]'
            }
        ]
        """
```

---

## 3. Database Schema & Pipeline Integration

### 3.1 Database Schema (`src/db/staging_db.py`)

```sql
-- 1. Sentence Patterns Catalog
CREATE TABLE IF NOT EXISTS sentence_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT UNIQUE NOT NULL,
    structure_json TEXT,
    example_en TEXT,
    example_vi TEXT,
    cefr_level TEXT
);

-- 2. N-N Pattern <-> Sentence Junction Table
CREATE TABLE IF NOT EXISTS pattern_sentences (
    pattern_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,
    matched_tokens_json TEXT,
    PRIMARY KEY (pattern_id, sentence_id),
    FOREIGN KEY (pattern_id) REFERENCES sentence_patterns (id) ON DELETE CASCADE,
    FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
);
```

### 3.2 Pipeline Step (`main.py`)
Function `run_pattern_step()`:
1. Fetches sentences from `sentences` table.
2. Runs `GrammarPatternExtractor.extract_patterns()` for each sentence.
3. Batch inserts pattern definitions into `sentence_patterns`.
4. Batch inserts mapping records into `pattern_sentences`.
5. Selects top representative example sentences (validated Vietnamese translation, 8–20 words length) to backfill `sentence_patterns.example_en` and `example_vi`.

### 3.3 Mobile SQLite Packaging (`src/export/sqlite_exporter.py`)
- Recreates `pattern_sentences` as a `WITHOUT ROWID` link table.
- Builds covering index `idx_pattern_sentences_pid` on `pattern_sentences(pattern_id, sentence_id)`.
- Ensures sub-1ms query response for fetching sentence pattern examples.

---

## 4. Testing & Verification Plan

1. **Unit Tests (`tests/test_pattern_extractor.py`):**
   - Test pattern extraction accuracy for representative A1–C2 sentences.
   - Verify token positions, structures, and CEFR level outputs.
2. **Integration Tests (`tests/test_pattern_pipeline.py`):**
   - Test `run_pattern_step()` on mock staging database.
   - Verify correct insertion into `sentence_patterns` and `pattern_sentences`.
   - Verify automatic example sentence selection logic.
3. **Mobile Performance Tests (`tests/test_sqlite_exporter.py`):**
   - Verify `pattern_sentences` is exported as `WITHOUT ROWID`.
   - Benchmark pattern lookup query speed (< 1.0 ms SLA).

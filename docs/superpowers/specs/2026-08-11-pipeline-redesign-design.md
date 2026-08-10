# Pipeline Redesign — DAG Architecture with DuckDB Staging

**Date:** 2026-08-11  
**Status:** Approved  
**Target runtime:** < 15 minutes (full pipeline)  

---

## 1. Executive Summary

Redesign `make run` từ monolithic sequential pipeline thành **DAG-based pipeline** với:

1. **Single-pass Kaikki stream** — 1 lần đọc 3.18GB, phân loại words/phrases/relations cùng lúc
2. **DuckDB staging layer** — analytics, analytics, bulk transform song song
3. **SQLite WAL mode** — final export tối ưu cho mobile
4. **Hybrid translator** — Argos Translate (local) primary, Google Translate fallback
5. **Deferred translation** — tách translate ra khỏi hot path, batch async
6. **Audio: core pack only** — generate cho 3000 words + example sentences

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VOCABCRAFT ENGINE v2.0                               │
│                     DAG-Based Pipeline Architecture                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐                                                           │
│  │  DATA LAYER  │  Kaikki JSONL, Tatoeba CSV, OpenSubtitles, EnViCorpora   │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │                   STAGING LAYER (DuckDB)                     │           │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌────────────┐ │           │
│  │  │ raw_    │  │ raw_     │  │ raw_       │  │ raw_       │ │           │
│  │  │ words   │  │ phrases  │  │ relations  │  │ sentences  │ │           │
│  │  └─────────┘  └──────────┘  └────────────┘  └────────────┘ │           │
│  │         │              │            │              │        │           │
│  │         ▼              ▼            ▼              ▼        │           │
│  │  ┌─────────────────────────────────────────────────────┐    │           │
│  │  │         TRANSFORM LAYER (parallel SQL)              │    │           │
│  │  │  • CEFR grading     • Lemmatization                 │    │           │
│  │  │  • Collocation extraction  • Word-sentence linking  │    │           │
│  │  │  • Topic mapping    • Inverse relation pass         │    │           │
│  │  └─────────────────────────────────────────────────────┘    │           │
│  │         │                                                   │           │
│  │         ▼                                                   │           │
│  │  ┌─────────────────────────────────────────────────────┐    │           │
│  │  │         ENRICHMENT LAYER (async Python)             │    │           │
│  │  │  • Vietnamese translation (Argos primary, Google FB)│    │           │
│  │  │  • Audio generation (core pack only)                │    │           │
│  │  │  • Reflex drill generation                          │    │           │
│  │  │  • Dialogue scenarios                               │    │           │
│  │  └─────────────────────────────────────────────────────┘    │           │
│  └──────────────────────────────────────────────────────────────┘           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │                   EXPORT LAYER (SQLite)                      │           │
│  │  ┌─────────────────────┐  ┌──────────────────────────────┐  │           │
│  │  │ english_dataset.db  │  │ core_3000.db                 │  │           │
│  │  │ (WAL mode, indexes) │  │ (curated pack + audio)       │  │           │
│  │  └─────────────────────┘  └──────────────────────────────┘  │           │
│  └──────────────────────────────────────────────────────────────┘           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. DAG Definition

```
graph TD
    subgraph Phase 0 — Setup
        A[Download Raw Data] --> B[Initialize DuckDB Staging]
        B --> C[Initialize SQLite Export]
    end

    subgraph Phase 1 — Single-Pass Ingestion
        D[Stream Kaikki JSONL<br/>3.18GB single pass] --> E[raw_words]
        D --> F[raw_phrases]
        D --> G[raw_relations + raw_topics]
        H[Tatoeba CSV] --> I[raw_sentences_tatoeba]
        J[OpenSubtitles] --> K[raw_sentences_opensubt]
        L[EnViCorpora] --> M[raw_sentences_envi]
    end

    subgraph Phase 2 — Transform (DuckDB SQL)
        E --> N[Apply CEFR Grading]
        I --> N
        K --> N
        M --> N
        N --> O[Lemmatize + Link Word-Sentence]
        N --> P[Extract Collocations]
        G --> Q[Build Inverse Relations]
        G --> R[Map Topics]
        F --> S[Grade + Deduplicate Phrases]
    end

    subgraph Phase 3 — Enrichment (Async Python)
        O --> T[Reflex Drill Generation]
        S --> T
        O --> U[Dialogue Scenarios]
        P --> V[VI Translation — Collocations]
        S --> W[VI Translation — Phrases]
        O --> X[VI Translation — Definitions]
        N --> Y[VI Translation — Words]
    end

    subgraph Phase 4 — Export
        O --> Z[SQLite words + definitions + sentences]
        Q --> Z
        R --> Z
        S --> Z
        P --> Z
        T --> Z
        U --> Z
        V --> Z
        W --> X
        X --> Z
        Y --> Z
    end

    subgraph Phase 5 — Core Pack
        Z --> AA[Select 3000 core words]
        AA --> AB[Quality Gates + Quarantine]
        AB --> AC[Generate Audio — Core Only]
        AC --> AD[Export core_3000.db]
    end
```

---

## 4. Module Structure

```
src/
├── pipeline/
│   ├── __init__.py
│   ├── dag.py              # DAG executor, dependency resolution
│   ├── registry.py         # Step registry, checkpoint tracking
│   └── context.py          # Shared context (config, connections, cache)
├── stages/
│   ├── __init__.py
│   ├── stage_1_ingest.py   # Single-pass Kaikki + corpora
│   ├── stage_2_transform.py # DuckDB SQL transforms
│   ├── stage_3_enrich.py    # NLP enrichment + translation
│   ├── stage_4_export.py    # SQLite packaging
│   └── stage_5_core_pack.py # Core pack builder
├── ingestion/
│   ├── kaikki_single_pass.py  # Replaces kaikki_parser + phrase_parser + relation_parser
│   ├── corpora.py             # Tatoeba + OpenSubtitles + EnViCorpora
│   └── downloader.py          # Parallel download
├── db/
│   ├── duckdb_manager.py   # Staging DuckDB (WAL, parallel reads)
│   └── sqlite_manager.py   # Export SQLite (WAL, optimized PRAGMAs)
├── nlp/
│   ├── ...                 # Existing modules (keep, minor changes)
│   └── translator_hybrid.py # Argos + Google hybrid
├── media/
│   └── ...                 # Existing audio generator
└── export/
    └── ...                 # Existing SQLite exporter
```

---

## 5. Key Design Decisions

### 5.1 Single-Pass Kaikki Stream

**Problem:** Hiện tại stream 3.18GB dump 3 lần (words, phrases, relations) → ~60 phút chỉ đọc file.

**Solution:** 1 lần đọc, phân loại vào cùng lúc.

```python
# src/ingestion/kaikki_single_pass.py

class KaikkiSinglePassParser:
    """Streams Kaikki dump once, yields categorized entries."""
    
    def parse_all(self) -> SinglePassResult:
        """Single-pass: classify each entry into words, phrases, relations."""
        for item in self._stream_jsonl():
            word = item.get("word", "")
            pos = item.get("pos", "")
            
            if " " in word:
                phrase = self._extract_phrase(item)
                if phrase:
                    yield "phrase", phrase
            else:
                entry = self._extract_word(item)
                if entry:
                    yield "word", entry
                
                relations = self._extract_relations(item)
                if relations:
                    yield "relations", relations
```

**Expected impact:** -40 minutes runtime.

### 5.2 DuckDB as Staging Layer

**Problem:** SQLite single-threaded inserts + per-row SELECT = chậm cho 1.4M+ definitions.

**Solution:** DuckDB cho staging, SQLite cho export.

**DuckDB configuration:**
```python
# src/db/duckdb_manager.py

PRAGMAS = [
    "PRAGMA threads = 0;",           # Auto-detect CPU cores
    "PRAGMA memory_limit = '8GB';",  # Adjust based on available RAM
    "PRAGMA enable_object_cache;",
    "PRAGMA enable_progress_bar;",
]
```

**Staging schema (DuckDB):**
- `raw_words` — lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level
- `raw_definitions` — word_id, definition_en, definition_vi, example, source
- `raw_phrases` — phrase, phrase_type, pos, cefr_level, definition_en, definition_vi, ipa
- `raw_relations` — word_id, relation_type, target_text, target_word_id, inverted, source
- `raw_topics` — word_id, topic, raw_topic
- `raw_sentences` — text_en, text_vi, difficulty_score, cefr_level, source

**Transform queries run in parallel:**
```sql
-- CEFR grading (vectorized)
UPDATE raw_words SET cefr_level = CASE
    WHEN frequency_rank <= 1000 THEN 'A1'
    WHEN frequency_rank <= 2500 THEN 'A2'
    WHEN frequency_rank <= 5000 THEN 'B1'
    WHEN frequency_rank <= 10000 THEN 'B2'
    WHEN frequency_rank <= 20000 THEN 'C1'
    ELSE 'C2'
END;

-- Inverse relations (set-based, not row-by-row)
INSERT INTO raw_relations
SELECT target_word_id AS word_id, 'hyponym' AS relation_type,
       w.lemma AS target_text, r.word_id AS target_word_id,
       1 AS inverted, r.source
FROM raw_relations r
JOIN raw_words w ON w.id = r.word_id
WHERE r.relation_type = 'hypernym' AND r.inverted = 0
  AND r.target_word_id IS NOT NULL;
```

### 5.3 SQLite Export Optimization

**Problem:** Mỗi batch commit riêng, không WAL mode trong khi ingest.

**Solution:** WAL mode + bulk transactions + in-memory cache.

```python
# src/db/sqlite_manager.py

BULK_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = OFF;",         # Safe for staging rebuilds
    "PRAGMA cache_size = -20000;",       # 20MB cache
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 268435456;",     # 256MB memory-mapped I/O
]

class SQLiteBulkWriter:
    """Batch writer with deferred commits and transaction coalescing."""
    
    def __init__(self, commit_every: int = 5):
        self.commit_every = commit_every
        self._batches_since_commit = 0
    
    def insert_batch(self, table: str, rows: List[dict]):
        self._executemany(table, rows)
        self._batches_since_commit += 1
        if self._batches_since_commit >= self.commit_every:
            self.conn.commit()
            self._batches_since_commit = 0
```

### 5.4 In-Memory Lemma Cache

**Problem:** Step 2 definitions gọi `get_word_id_by_lemma()` → ~1.4M SELECT queries.

**Solution:** Load lemma→id map một lần vào dict (O(1) lookup).

```python
class LemmaCache:
    def __init__(self, conn):
        self._map: Dict[str, int] = {
            row[1]: row[0] 
            for row in conn.execute("SELECT id, lemma FROM words").fetchall()
        }
    
    def get_id(self, lemma: str) -> Optional[int]:
        return self._map.get(lemma.lower())
    
    def add(self, lemma: str, word_id: int):
        self._map[lemma.lower()] = word_id
```

### 5.5 Hybrid Vietnamese Translator

**Problem:** Google Translate chỉ, rate limit, network latency, không offline.

**Solution:** Argos Translate (local) primary, Google Translate fallback.

```python
# src/nlp/translator_hybrid.py

class HybridTranslator:
    def __init__(self):
        self._local = ArgosTranslator() if argos_available else None
        self._fallback = GoogleTranslator()
    
    def translate(self, text: str) -> str:
        if self._local:
            result = self._local.translate(text)
            if self._validator.is_vietnamese(result):
                return result
        
        result = self._fallback.translate(text)
        if self._validator.is_vietnamese(result):
            return result
        
        return ""
```

**Argos Translate:**
- Offline, no rate limits
- ~50-200ms per call (vs Google ~500ms-2s)
- Quality acceptable for short phrases/definitions
- Setup: `pip install argostranslate` + download en-vi model (~30MB)

### 5.6 Deferred Translation

**Problem:** Translation (network blocking) xen kẽ trong extraction pipeline.

**Solution:** Tách 2 phases:
1. **Extract phase** — Chỉ extract text, không translate. Write placeholder NULL.
2. **Backfill phase** — Batch translate tất cả NULL cùng lúc, async.

```python
# Phase A: Extract (no network)
for phrase in extract_collocations():
    db.insert_phrase(phrase)  # meaning_vi = NULL

# Phase B: Batch backfill (async, parallel)
async def backfill_translations():
    null_rows = db.get_null_translations()
    tasks = [translate_batch(chunk) for chunk in chunks(null_rows, 100)]
    await asyncio.gather(*tasks)
```

### 5.7 Parallel Download

**Problem:** `download_all_raw_data()` tải tuần tự 7+ file.

**Solution:** `concurrent.futures.ThreadPoolExecutor` cho independent downloads.

```python
# src/ingestion/downloader.py

def download_all(urls: list[DownloadTask]):
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download_one, task): task for task in urls}
        for future in as_completed(futures):
            task = futures[future]
            future.result()  # Raise on failure
```

### 5.8 DAG Executor

```python
# src/pipeline/dag.py

class PipelineDAG:
    """Executes pipeline steps respecting dependency order."""
    
    def __init__(self):
        self._steps: Dict[str, PipelineStep] = {}
        self._dependencies: Dict[str, Set[str]] = {}
    
    def add_step(self, name: str, func: Callable, depends: Set[str] = None):
        self._steps[name] = func
        self._dependencies[name] = depends or set()
    
    def execute(self, context: PipelineContext):
        completed = set()
        ready = self._find_ready(completed)
        
        while ready:
            # Run independent steps in parallel
            with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = {
                    pool.submit(self._run_step, name, context): name 
                    for name in ready
                }
                for future in as_completed(futures):
                    name = futures[future]
                    future.result()
                    completed.add(name)
            
            ready = self._find_ready(completed)
    
    def _find_ready(self, completed: Set[str]) -> Set[str]:
        return {
            name for name, deps in self._dependencies.items()
            if name not in completed and deps.issubset(completed)
        }
```

---

## 6. Stage Breakdown

### Stage 1: Ingest (Target: < 3 min)

| Step | Action | Parallel? |
|------|--------|-----------|
| 1a | Download raw data (7 files) | ✅ 4 workers |
| 1b | Stream Kaikki → DuckDB raw tables | Single-thread (I/O bound) |
| 1c | Load Tatoeba CSV → DuckDB | ✅ DuckDB parallel CSV reader |
| 1d | Load OpenSubtitles + EnViCorpora → DuckDB | ✅ DuckDB parallel |

**New Kaikki parser:**
- Uses DuckDB's native JSONL reader when possible
- Falls back to single-pass Python iterator for custom filtering

### Stage 2: Transform (Target: < 2 min)

| Step | Action | Method |
|------|--------|--------|
| 2a | CEFR grading | SQL UPDATE (vectorized) |
| 2b | Lemmatization + word-sentence link | spaCy pipe (batch) + SQL |
| 2c | Collocation extraction | spaCy pipe + SQL GROUP BY |
| 2d | Inverse relations | SQL INSERT FROM SELECT |
| 2e | Topic mapping | SQL UPDATE with TopicMapper UDF |

### Stage 3: Enrich (Target: < 5 min)

| Step | Action | Method |
|------|--------|--------|
| 3a | Reflex drill generation | Batch SQL + Python |
| 3b | Dialogue scenarios | Static templates (fast) |
| 3c | VI translations (definitions) | Async batch (Argos → Google) |
| 3d | VI translations (collocations) | Async batch |
| 3e | VI translations (phrases) | Async batch |
| 3f | Audio generation (core pack) | Async edge-tts, 20 concurrent |

### Stage 4: Export (Target: < 3 min)

| Step | Action | Method |
|------|--------|--------|
| 4a | DuckDB → SQLite bulk COPY | `ATTACH` + `INSERT SELECT` |
| 4b | Create indexes | `CREATE INDEX IF NOT EXISTS` |
| 4c | ANALYZE + VACUUM | SQLite optimization |
| 4d | Benchmark + verify | FK check + query speed |

### Stage 5: Core Pack (Target: < 2 min)

| Step | Action | Method |
|------|--------|--------|
| 5a | Select 3000 words | SQL + quality gates |
| 5b | Generate audio | Async edge-tts |
| 5c | Export core_3000.db | SQLite attach + COPY |

---

## 7. Makefile Targets (New)

```makefile
# ── Setup & Download ──
make setup                  # venv + deps + models
make download-data          # Raw datasets (parallel)
make corpus-download        # Parallel corpora

# ── Pipeline ──
make run                    # Full pipeline (auto-resume via DAG checkpoints)
make run-fresh              # Force re-run everything
make run-step STEP=ingest   # Run single stage: ingest|transform|enrich|export|pack

# ── Development ──
make test                   # Pytest suite
make benchmark              # Runtime benchmark
make profile                # Profile slow steps
make clean-db               # Delete output DBs
make clean                  # Full clean
```

---

## 8. Checkpoint & Resume

Mỗi stage tự động checkpoint sau khi hoàn thành. Resume = skip completed stages.

```
data/processed/
├── checkpoint_ingest.json     # {"completed": true, "timestamp": ...}
├── checkpoint_transform.json
├── checkpoint_enrich.json
├── checkpoint_export.json
└── checkpoint_pack.json
```

DAG executor đọc checkpoints, auto-skip stages đã hoàn thành (trừ khi `--force-reset`).

---

## 9. Error Handling

| Scenario | Behavior |
|----------|----------|
| Stage fails mid-way | Log error, save partial checkpoint, exit with code 1 |
| Re-run after failure | Resume from last successful stage |
| Translation timeout | Retry 3x with exponential backoff, then leave NULL |
| Disk full during VACUUM | Raise clear error, suggest `make clean-db` |
| Network down for download | Retry 3x, skip if already partial (Range resume) |

---

## 10. Performance Targets

| Metric | Current | Target |
|--------|---------|--------|
| Full pipeline runtime | ~2-3 hours | < 15 min |
| Kaikki stream passes | 3 | 1 |
| DB insert throughput | ~5K rows/sec | ~50K rows/sec |
| Translation throughput | ~2/sec | ~50/sec (local) |
| Audio generation | 100 files | 3000+ files (core pack) |
| Final DB query latency | < 5ms | < 5ms (maintained) |

---

## 11. Migration Path

1. **Phase 1**: Implement `KaikkiSinglePassParser`, test correctness
2. **Phase 2**: Implement DuckDB staging, migrate Stage 1-2
3. **Phase 3**: Implement SQLite bulk export, migrate Stage 3-4
4. **Phase 4**: Add hybrid translator
5. **Phase 5**: Implement DAG executor, wire everything together
6. **Phase 6**: Benchmark, profile, optimize

---

## 12. Open Questions

1. **DuckDB version**: Pin to latest stable (1.1.x) or track latest?
2. **Argos Translate model**: Bundle in repo or download on `make setup`?
3. **DuckDB persistence**: Keep staging.duckdb file between runs or rebuild fresh?
4. **Polars integration**: Use Polars as intermediate DataFrame library (faster than pandas for transforms)?

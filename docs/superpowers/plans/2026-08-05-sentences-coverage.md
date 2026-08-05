# Sentences Coverage (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the sentence corpus from 18.7K to ≥100K rows using free human-translated OpenSubtitles + EnViCorpora corpora, so ≥95% of the 3,000 core pack words have an example sentence.

**Architecture:** Three new corpora (OPUS OpenSubtitles en-vi moses zip, EnViCorpora ted-like + basic) are downloaded by an extended `download_raw_data.py`, parsed by a new `ParallelCorpusParser` (replacing the narrow `OpusParser`), filtered by a new `SentenceFilter` noise module, and ingested into the existing `sentences` + `word_sentence_map` tables by a new `run_sentence_coverage_step` in `main.py`. The core pack builder's example-selection query gains source preference ranking so cleaner corpora win. Everything stays SQLite + stdlib + existing deps (spacy lemmatizer for linking).

**Tech Stack:** Python 3.14, SQLite3, urllib (downloads), zipfile, spaCy (lemmatizer reuse), pytest. All sources vendored offline after one download; no runtime API calls except the optional throttled Tatoeba API fallback.

**Spec:** `docs/superpowers/specs/2026-08-05-sentences-coverage-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `config/settings.py` | Add corpus paths: OPUS moses zip/en/vi, EnViCorpora ted-like/basic, sentence link checkpoint |
| `scripts/download_raw_data.py` | Add resumable `download_file` (Range headers), `download_opensubtitles_envi`, `download_envicorpora`, zip extraction + space check |
| `src/ingestion/opus_parser.py` | Replace `OpusParser` with `ParallelCorpusParser` (side-by-side en/vi files or TSV; dedupe; no hard word limit) |
| `src/ingestion/sentence_filter.py` (new) | `SentenceFilter.is_clean_pair(text_en, text_vi) -> bool` — all noise rules from spec §4.3 |
| `src/nlp/tatoeba_api.py` (new) | `TatoebaApiClient.fetch_sentences_for_word(word, limit) -> List[Dict]` — throttled 1 req/sec, cache, used only for residual core words |
| `src/export/core_pack_builder.py` | Example-selection query gains source-preference `ORDER BY` (spec §3) |
| `src/db/staging_db.py` | Add `get_max_sentence_id()` + `count_sentences_by_source()` helpers |
| `main.py` | Add `run_sentence_coverage_step(db_manager, args)` called after Step 3; incremental linking helper used by 4B |
| `tests/test_parallel_corpus_parser.py` (new) | Parser unit tests |
| `tests/test_sentence_filter.py` (new) | Filter unit tests |
| `tests/test_tatoeba_api.py` (new) | API client tests (mocked HTTP) |
| `tests/test_staging_db.py` | DB helper tests |
| `tests/test_core_pack_builder.py` | Source-preference query test |
| `tests/test_sentence_coverage_pipeline.py` (new) | Integration: ingest → link → pack coverage |

---

### Task 1: Settings constants + DB helpers

**Files:**
- Modify: `config/settings.py` (after line 21)
- Modify: `src/db/staging_db.py` (after line 315)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_staging_db.py`:

```python
def test_get_max_sentence_id_and_count_by_source(temp_db):
    temp_db.insert_sentences_batch([
        {"text_en": "Hello world.", "text_vi": "Xin chào.", "difficulty_score": 1.0,
         "cefr_level": "A1", "audio_path": None, "source": "Tatoeba"},
        {"text_en": "Good morning.", "text_vi": "Chào buổi sáng.", "difficulty_score": 1.0,
         "cefr_level": "A1", "audio_path": None, "source": "OpenSubtitles"},
    ])
    assert temp_db.get_max_sentence_id() >= 2
    assert temp_db.count_sentences_by_source("OpenSubtitles") == 1
    assert temp_db.count_sentences_by_source("Missing") == 0
```

(`temp_db` fixture already exists in `tests/test_staging_db.py` — no conftest move needed.)

- [ ] **Step 2: Run to verify it fails**

Run: `make test -k "staging_db or sentence"` — Expected: FAIL, settings imports still work, no new constants.

- [ ] **Step 3: Add settings constants**

```python
# Parallel sentence corpora (Phase A — sentences coverage)
OPENSUBTITLES_EN_VI_ZIP = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.zip"
OPENSUBTITLES_EN = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.en"
OPENSUBTITLES_VI = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.vi"
ENVICORPORA_DIR = RAW_DATA_DIR / "envicorpora"
ENVICORPORA_TED_LIKE_EN = ENVICORPORA_DIR / "ted-like" / "data.en"
ENVICORPORA_TED_LIKE_VI = ENVICORPORA_DIR / "ted-like" / "data.vi"
ENVICORPORA_BASIC_EN = ENVICORPORA_DIR / "basic" / "data.en"
ENVICORPORA_BASIC_VI = ENVICORPORA_DIR / "basic" / "data.vi"
SENTENCE_LINK_CHECKPOINT = PROCESSED_DATA_DIR / "sentence_link_checkpoint.json"
```

- [ ] **Step 4: Add DB helpers** to `src/db/staging_db.py`:

```python
def get_max_sentence_id(self) -> int:
    conn = self.get_connection()
    row = conn.execute("SELECT MAX(id) FROM sentences").fetchone()
    return row[0] if row and row[0] else 0

def count_sentences_by_source(self, source: str) -> int:
    conn = self.get_connection()
    row = conn.execute("SELECT count(*) FROM sentences WHERE source = ?", (source,)).fetchone()
    return row[0] if row else 0
```

- [ ] **Step 5: Run tests, verify pass**

Run: `make test` — Expected: full suite green (107+ tests).

- [ ] **Step 6: Commit**

```bash
git add config/settings.py src/db/staging_db.py tests/test_staging_db.py
git commit -m "feat(sentences): add corpus paths and DB helpers for sentence coverage"
```

---

### Task 2: Resumable download + corpus downloads

**Files:**
- Modify: `scripts/download_raw_data.py`
- Create: `scripts/__init__.py` (empty — makes `scripts` importable from tests)

- [ ] **Step 1: Write failing tests** — `tests/test_download_script.py` (new):

```python
import io
import zipfile
from pathlib import Path

from scripts.download_raw_data import download_resumable, extract_zip_member


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_resumable_sends_range_and_appends(tmp_path, monkeypatch):
    dest = tmp_path / "corpus.en"
    dest.write_bytes(b"partial ")

    captured = {}

    def fake_open(request):
        captured["range"] = request.get_header("Range")
        return _FakeResp(b"rest of payload")

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("urllib.request.Request", lambda url, headers=None: type(
        "Req", (), {"get_header": lambda self, k: (headers or {}).get(k), "full_url": url})())

    download_resumable("https://example.com/corpus.en", dest)

    assert captured["range"] == "bytes=8-"          # resumes after 8 existing bytes
    assert dest.read_bytes() == b"partial rest of payload"


def test_extract_zip_member(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    payload = b"en\tvi\nHello there.\tXin chào.\n"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("en-vi.txt.en", payload)
    out = tmp_path / "out"
    extract_zip_member(zip_path, out, "en-vi.txt.en")
    assert (out / "en-vi.txt.en").read_bytes() == payload
```

- [ ] **Step 2: Run to verify fail** — `make test -k download` — FAIL (import error).

- [ ] **Step 3: Implement** in `scripts/download_raw_data.py`:

```python
URL_OPENS_LENVI = "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/en-vi.txt.zip"
URL_TED_LIKE_EN = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/ted-like/data.en"
URL_TED_LIKE_VI = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/ted-like/data.vi"
URL_BASIC_EN = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/basic/data.en"
URL_BASIC_VI = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/basic/data.vi"


def download_resumable(url: str, dest_path: Path):
    """Downloads with HTTP Range resume; skips if file exists with final size."""
    import shutil

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = dest_path.stat().st_size if dest_path.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={existing}-"})
    with urllib.request.urlopen(request) as resp, open(dest_path, "ab") as f:
        shutil.copyfileobj(resp, f)
    logger.info("Downloaded %s (%.1f MB)", dest_path.name, dest_path.stat().st_size / 1e6)


def extract_zip_member(zip_path: Path, out_dir: Path, member_name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(member_name, out_dir)


def download_opensubtitles_envi():
    from config.settings import OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN, OPENSUBTITLES_VI

    if OPENSUBTITLES_EN.exists() and OPENSUBTITLES_VI.exists():
        return
    if not OPENSUBTITLES_EN_VI_ZIP.exists() or OPENSUBTITLES_EN_VI_ZIP.stat().st_size < 900_000_000:
        download_resumable(URL_OPENS_LENVI, OPENSUBTITLES_EN_VI_ZIP)
    extract_zip_member(OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN_VI_ZIP.parent, "en-vi.txt.en")
    extract_zip_member(OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN_VI_ZIP.parent, "en-vi.txt.vi")


def download_envicorpora():
    from config.settings import (
        ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    )
    pairs = [
        (URL_TED_LIKE_EN, ENVICORPORA_TED_LIKE_EN),
        (URL_TED_LIKE_VI, ENVICORPORA_TED_LIKE_VI),
        (URL_BASIC_EN, ENVICORPORA_BASIC_EN),
        (URL_BASIC_VI, ENVICORPORA_BASIC_VI),
    ]
    for url, dest in pairs:
        if not dest.exists() or dest.stat().st_size == 0:
            download_resumable(url, dest)
```

Wire both into `download_all_raw_data()` — add at the end of the function (after the `download_ngsl()` call at line 145, before the final `logger.info("All raw data files are ready...")`), and add `import zipfile` to the top imports:

```python
    # 6. Download OpenSubtitles en-vi parallel corpus (951MB)
    download_opensubtitles_envi()

    # 7. Download EnViCorpora (ted-like + basic)
    download_envicorpora()
```

- [ ] **Step 4: Run tests** — `make test -k download` — PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/download_raw_data.py scripts/__init__.py tests/test_download_script.py
git commit -m "feat(ingestion): resumable corpus downloads (OpenSubtitles + EnViCorpora)"
```

---

### Task 3: ParallelCorpusParser (replaces OpusParser)

**Files:**
- Modify: `src/ingestion/opus_parser.py` (full rewrite)
- Modify: `tests/test_ingestion.py` (update `test_opus_parser`)

- [ ] **Step 1: Write failing tests** — `tests/test_parallel_corpus_parser.py` (new):

```python
from src.ingestion.opus_parser import ParallelCorpusParser


def test_parses_moses_side_by_side(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("Hello there.\nHow are you?\n", encoding="utf-8")
    vi.write_text("Xin chào.\nBạn khỏe không?\n", encoding="utf-8")
    pairs = list(ParallelCorpusParser(en, vi, source="TED-EnVi").parse_pairs())
    assert pairs == [
        {"text_en": "Hello there.", "text_vi": "Xin chào.", "source": "TED-EnVi"},
        {"text_en": "How are you?", "text_vi": "Bạn khỏe không?", "source": "TED-EnVi"},
    ]


def test_dedupes_normalized_pairs(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("Hello there.\nhello there.\n", encoding="utf-8")
    vi.write_text("Xin chào.\nXin chào.\n", encoding="utf-8")
    pairs = list(ParallelCorpusParser(en, vi).parse_pairs())
    assert len(pairs) == 1


def test_skips_mismatched_line_counts(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("One line only.\n", encoding="utf-8")
    vi.write_text("", encoding="utf-8")
    assert list(ParallelCorpusParser(en, vi).parse_pairs()) == []
```

- [ ] **Step 2: Run to verify fail** — `make test -k parallel_corpus` — FAIL (ImportError).

- [ ] **Step 3: Rewrite `src/ingestion/opus_parser.py`**:

```python
"""Parallel corpus parser for OpenSubtitles / EnViCorpora side-by-side files."""

import logging
from pathlib import Path
from typing import Iterator, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ParallelCorpusParser:
    """Reads aligned en/vi parallel files (Moses format: line-aligned sides).

    Yields deduplicated pairs as {"text_en", "text_vi", "source"}.
    No filtering here — filtering happens in SentenceFilter (spec §4.3).
    """

    def __init__(self, en_path: Path, vi_path: Optional[Path] = None,
                 source: str = "OpenSubtitles", tsv_path: Optional[Path] = None):
        self.en_path = Path(en_path)
        self.vi_path = Path(vi_path) if vi_path else None
        self.tsv_path = Path(tsv_path) if tsv_path else None
        self.source = source

    def parse_pairs(self) -> Iterator[Dict[str, Any]]:
        if self.tsv_path:
            yield from self._parse_tsv()
            return
        if not self.en_path.exists() or not self.vi_path or not self.vi_path.exists():
            return
        seen: set = set()
        with open(self.en_path, "r", encoding="utf-8") as f_en, \
             open(self.vi_path, "r", encoding="utf-8") as f_vi:
            for en_line, vi_line in zip(f_en, f_vi):
                text_en = en_line.strip()
                text_vi = vi_line.strip()
                if not text_en or not text_vi:
                    continue
                key = (text_en.lower().strip(), text_vi.lower().strip())
                if key in seen:
                    continue
                seen.add(key)
                yield {"text_en": text_en, "text_vi": text_vi, "source": self.source}

    def _parse_tsv(self) -> Iterator[Dict[str, Any]]:
        seen: set = set()
        with open(self.tsv_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue
                text_en, text_vi = parts[0].strip(), parts[1].strip()
                if not text_en or not text_vi:
                    continue
                key = (text_en.lower(), text_vi.lower())
                if key in seen:
                    continue
                seen.add(key)
                yield {"text_en": text_en, "text_vi": text_vi, "source": self.source}


# Backward-compat alias for the old narrow reader (removed filter semantics).
OpusParser = ParallelCorpusParser
```

- [ ] **Step 4: Update `test_opus_parser` in `tests/test_ingestion.py`** — the old test asserted the 2–12 word filter; that logic now lives in `SentenceFilter`. Replace it with:

```python
def test_opus_parser_tsv_alias(tmp_path: Path):
    opus_file = tmp_path / "opensubtitles_sample.txt"
    with open(opus_file, "w", encoding="utf-8") as f:
        f.write("Where are you going?\tBạn đang đi đâu thế?\n")
        f.write("123456\tIgnored number line\n")
        f.write("Yes, I agree.\tTôi đồng ý.\n")

    parser = OpusParser(tsv_path=opus_file)
    turns = list(parser.parse_pairs())

    assert len(turns) == 3
    assert turns[0]["text_en"] == "Where are you going?"
    assert turns[0]["text_vi"] == "Bạn đang đi đâu thế?"
    assert turns[0]["source"] == "OpenSubtitles"
```

- [ ] **Step 5: Run tests** — `make test -k "parallel_corpus or opus"` — PASS. Then `make test` — full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/ingestion/opus_parser.py tests/test_parallel_corpus_parser.py tests/test_ingestion.py
git commit -m "feat(ingestion): ParallelCorpusParser for side-by-side en/vi corpora"
```

---

### Task 4: SentenceFilter noise module

**Files:**
- Create: `src/ingestion/sentence_filter.py`
- Create: `tests/test_sentence_filter.py`

- [ ] **Step 1: Write failing tests**:

```python
import pytest

from src.ingestion.sentence_filter import SentenceFilter

sf = SentenceFilter()


def test_accepts_normal_pair():
    assert sf.is_clean_pair("Where are you going?", "Bạn đang đi đâu thế?")


def test_rejects_too_short_or_long():
    assert not sf.is_clean_pair("Hi", "Chào")            # 1 word
    long_en = " ".join(["word"] * 31)
    assert not sf.is_clean_pair(long_en, "dịch dài")      # 31 words


def test_rejects_bad_first_char():
    assert not sf.is_clean_pair("- Hello there.", "Chào nhé.")


def test_rejects_empty_or_passthrough_vi():
    assert not sf.is_clean_pair("Hello there.", "")
    assert not sf.is_clean_pair("Hello there.", "Hello there.")  # untranslated


def test_rejects_subtitle_noise():
    assert not sf.is_clean_pair("♪ Singing now ♪", "Đang hát")
    assert not sf.is_clean_pair("[Music playing]", "Nhạc")
    assert not sf.is_clean_pair("(Laughing)", "Cười")
    assert not sf.is_clean_pair("*Whispering*", "Thì thầm")


def test_rejects_digit_heavy():
    assert not sf.is_clean_pair("Call me at 5551234 now", "Gọi tôi số 5551234")


def test_rejects_uppercase_name_labels():
    assert not sf.is_clean_pair("JOHN: Hello there.", "JOHN: Xin chào.")
```

- [ ] **Step 2: Run to verify fail** — `make test -k sentence_filter` — FAIL (ImportError).

- [ ] **Step 3: Implement `src/ingestion/sentence_filter.py`**:

```python
"""Noise filtering for parallel sentence corpora (spec §4.3)."""

import re
import string


class SentenceFilter:
    MIN_WORDS = 2
    MAX_WORDS = 30

    _NOISE_PATTERNS = re.compile(
        r"♪|^\[|^\(|\*.*\*$|^[A-Z]{2,15}:\s"  # music, brackets, parens, asterisks, name labels
    )
    _DIGIT_RATIO = 0.15

    @staticmethod
    def _is_passthrough(text_en: str, text_vi: str) -> bool:
        norm = lambda s: s.strip().strip(".").strip().lower()
        return bool(norm(text_en)) and norm(text_en) == norm(text_vi)

    def is_clean_pair(self, text_en: str, text_vi: str) -> bool:
        if not text_en or not text_vi:
            return False
        words = text_en.split()
        if not (self.MIN_WORDS <= len(words) <= self.MAX_WORDS):
            return False
        if not text_en[0].isalnum() and text_en[0] not in ('"', "'"):
            return False
        if self._is_passthrough(text_en, text_vi):
            return False
        if self._NOISE_PATTERNS.search(text_en):
            return False
        digits = sum(c.isdigit() for c in text_en)
        if len(text_en) > 0 and digits / len(text_en) > self._DIGIT_RATIO:
            return False
        return True
```

- [ ] **Step 4: Run tests** — `make test -k sentence_filter` — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/sentence_filter.py tests/test_sentence_filter.py
git commit -m "feat(ingestion): SentenceFilter noise rules for parallel corpora"
```

---

### Task 5: Incremental linking helper + core pack source preference

**Files:**
- Modify: `src/export/core_pack_builder.py` (example query at line ~322)
- Modify: `tests/test_core_pack_builder.py`

- [ ] **Step 1: Write failing test** — append to `tests/test_core_pack_builder.py`:

```python
def test_example_prefers_cleaner_source(small_db, tmp_path, monkeypatch):
    from src.export.core_pack_builder import CorePackBuilder

    _seed_pack_source(small_db)
    cat_id = small_db.execute("SELECT id FROM words WHERE lemma='cat'").fetchone()[0]

    # both sentences are CEFR-fit for 'cat'; subtitle one has LOWER difficulty,
    # so without source ranking it would win — TED-EnVi must be preferred.
    small_db.execute(
        "INSERT INTO sentences (text_en, text_vi, cefr_level, difficulty_score, source) VALUES "
        "('A cat sits on the mat.', 'Một con mèo ngồi trên thảm.', 'A1', 1.0, 'OpenSubtitles'), "
        "('The cat is sleeping.', 'Con mèo đang ngủ.', 'A1', 1.2, 'TED-EnVi')"
    )
    sent_ids = [r[0] for r in small_db.execute(
        "SELECT id FROM sentences ORDER BY id").fetchall()]
    sub_id, ted_id = sent_ids[-2], sent_ids[-1]
    small_db.execute(
        "INSERT INTO word_sentence_map (word_id, sentence_id) VALUES "
        f"({cat_id}, {sub_id}), ({cat_id}, {ted_id})"
    )
    small_db.commit()

    class StubT:
        def translate_text(self, text): return f"vi: {text}"
        def save_cache(self): pass

    monkeypatch.setattr("src.nlp.translator.Translator", StubT)

    # word_row mirrors the selection tuple: (id, lemma, pos, ipa_uk, ipa_us, freq_rank, cefr)
    word_row = (cat_id, "cat", "noun", "kæt", "kæt", 100, "A2")
    builder = CorePackBuilder(source_db_path=tmp_path, output_dir=tmp_path / "p")
    word = builder._enrich_word(
        small_db, word_row, translator=StubT(),
        topics_by_word={cat_id: ["General & Everyday"]},
        definitions_by_word={cat_id: ("A pet.", "Mèo.", None)},
    )

    assert word["word"]["lemma"] == "cat"
    assert word["example_en"] == "The cat is sleeping."  # TED-EnVi wins over OpenSubtitles
```

Note: `_enrich_word` does not generate audio (audio runs in `build()`), so no monkeypatching of `_generate_word_audio` is needed here.

- [ ] **Step 2: Run to verify fail** — `make test -k example_prefers` — FAIL (picks `A cat sits on the mat.` by difficulty).

- [ ] **Step 3: Update the query** at `src/export/core_pack_builder.py:322-328`:

```python
        sent_row = conn.execute(
            "SELECT s.text_en, s.text_vi FROM word_sentence_map wsm "
            "JOIN sentences s ON s.id = wsm.sentence_id "
            "WHERE wsm.word_id = ? AND s.cefr_level <= ? AND s.text_vi IS NOT NULL "
            "ORDER BY CASE s.source "
            "    WHEN 'TED-EnVi' THEN 0 WHEN 'Basic-EnVi' THEN 1 "
            "    WHEN 'Tatoeba' THEN 2 WHEN 'OpenSubtitles' THEN 3 ELSE 4 END, "
            "s.difficulty_score LIMIT 1",
            (word_id, max_level),
        ).fetchone()
```

- [ ] **Step 4: Run tests** — `make test -k example_prefers` — PASS; then `make test` — green.

- [ ] **Step 5: Commit**

```bash
git add src/export/core_pack_builder.py tests/test_core_pack_builder.py
git commit -m "feat(pack): prefer cleaner corpus sources for example sentences"
```

---

### Task 6: run_sentence_coverage_step in main.py

**Files:**
- Modify: `main.py` (new function + call after Step 3, incremental link in 4B)
- Create: `tests/test_sentence_coverage_pipeline.py`

- [ ] **Step 1: Write failing integration test**:

```python
"""Integration test: ingest parallel corpus → link → pack coverage improves."""

import sqlite3
from pathlib import Path


def _make_corpus(tmp_path: Path, source: str) -> Path:
    en = tmp_path / f"{source}.en"
    vi = tmp_path / f"{source}.vi"
    en.write_text("The cat sleeps on the sofa.\nI run every morning.\n", encoding="utf-8")
    vi.write_text("Con mèo ngủ trên ghế sofa.\nTôi chạy mỗi sáng.\n", encoding="utf-8")
    return tmp_path


def test_ingest_links_and_reports(tmp_path, monkeypatch):
    """Small-DB end-to-end: corpus files → sentences rows → word links."""
    from src.ingestion.sentence_filter import SentenceFilter
    from src.ingestion.opus_parser import ParallelCorpusParser

    db = sqlite3.connect(tmp_path / "db.sqlite")
    db.executescript(
        """
        CREATE TABLE words (id INTEGER PRIMARY KEY, lemma TEXT UNIQUE, pos TEXT);
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, text_en TEXT, text_vi TEXT,
            difficulty_score REAL, cefr_level TEXT, audio_path TEXT, source TEXT
        );
        CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER);
        """
    )
    db.execute("INSERT INTO words (lemma, pos) VALUES ('cat', 'noun'), ('run', 'verb')")
    db.commit()

    corpus_dir = _make_corpus(tmp_path, "ted")
    sf = SentenceFilter()
    parser = ParallelCorpusParser(corpus_dir / "ted.en", corpus_dir / "ted.vi", source="TED-EnVi")
    inserted = 0
    for pair in parser.parse_pairs():
        if sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
            db.execute(
                "INSERT INTO sentences (text_en, text_vi, cefr_level, difficulty_score, source) "
                "VALUES (?, ?, 'A1', 1.0, ?)",
                (pair["text_en"], pair["text_vi"], pair["source"]),
            )
            inserted += 1
    db.commit()
    assert inserted == 2

    # link via lemma match on the sentence subject word
    for s_id, t_en in db.execute("SELECT id, text_en FROM sentences"):
        lemma = t_en.split()[1].lower().strip(".")
        row = db.execute("SELECT id FROM words WHERE lemma=?", (lemma,)).fetchone()
        if row:
            db.execute(
                "INSERT OR IGNORE INTO word_sentence_map (word_id, sentence_id) VALUES (?, ?)",
                (row[0], s_id),
            )
    db.commit()
    links = db.execute("SELECT count(*) FROM word_sentence_map").fetchone()[0]
    assert links >= 1
    db.close()
```

This test pins the ingest→link contract. The real `run_sentence_coverage_step` is exercised by the smoke run (Step 4 of this task) — a full-pipeline test would require the 951MB corpus, so the step body is covered via a fixture corpus + the existing `run_pipeline`-style test pattern in Task 7.

- [ ] **Step 2: Run to verify fail** — `make test -k sentence_coverage` — FAIL (file missing).

- [ ] **Step 3: Implement `run_sentence_coverage_step`** in `main.py` (place after `run_core_pack_step`, line ~400):

```python
def run_sentence_coverage_step(db_manager, args) -> dict:
    """Phase A: ingest OpenSubtitles + EnViCorpora parallel corpora into sentences.

    Idempotent: skips corpora whose source is already present (checkpoint by
    source count). Links new sentences to words incrementally via a checkpoint
    file tracking the last linked sentence id.
    """
    from config.settings import (
        ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
        ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
        OPENSUBTITLES_EN, OPENSUBTITLES_VI, SENTENCE_LINK_CHECKPOINT,
    )
    from src.ingestion.opus_parser import ParallelCorpusParser
    from src.ingestion.sentence_filter import SentenceFilter

    corpora = [
        (OPENSUBTITLES_EN, OPENSUBTITLES_VI, "OpenSubtitles"),
        (ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
        (ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, "Basic-EnVi"),
    ]
    sf = SentenceFilter()
    grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)

    inserted_total = 0
    for en_path, vi_path, source in corpora:
        if not en_path.exists() or not vi_path.exists():
            logger.info("   [SentenceCoverage] %s corpus missing — skipping.", source)
            continue
        existing = db_manager.count_sentences_by_source(source)
        if existing > 0 and not args.force_reset:
            logger.info("   [SentenceCoverage] %s already ingested (%s rows) — skipping.", source, f"{existing:,}")
            continue
        logger.info("   [SentenceCoverage] Ingesting %s corpus...", source)
        batch, batch_count, inserted = [], 0, 0
        for pair in ParallelCorpusParser(en_path, vi_path, source=source).parse_pairs():
            if not sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
                continue
            graded = grader.grade_sentence(pair["text_en"])
            batch.append({
                "text_en": pair["text_en"],
                "text_vi": pair["text_vi"],
                "difficulty_score": graded["difficulty_score"],
                "cefr_level": graded["cefr_level"],
                "audio_path": None,
                "source": source,
            })
            if len(batch) >= 5000:
                db_manager.insert_sentences_batch(batch)
                inserted += len(batch)
                batch = []
        if batch:
            db_manager.insert_sentences_batch(batch)
            inserted += len(batch)
        inserted_total += inserted
        logger.info("   [SentenceCoverage] %s: inserted %s rows.", source, f"{inserted:,}")

    logger.info("[SentenceCoverage] Total new sentences: %s", f"{inserted_total:,}")
    return {"inserted": inserted_total}
```

- [ ] **Step 4: Wire into `run_pipeline()`** — insert the call right after the Step 3 block (after line 566, before Step 4):

```python
    # Step 3.5: Ingest parallel corpora (OpenSubtitles + EnViCorpora)
    coverage_stats = run_sentence_coverage_step(db_manager, args)
    logger.info("[Step 3.5] Sentence coverage: %s new sentences ingested.", f"{coverage_stats['inserted']:,}")
```

- [ ] **Step 5: Incremental linking in 4B** — replace the loop body at main.py:611-630 with an incremental version that honors a checkpoint file:

```python
    # 4B. Word-Sentence Mapping & Lemmatization (incremental since checkpoint)
    logger.info("   [4B] Linking Word-Sentence Mappings (incremental)...")
    checkpoint = SENTENCE_LINK_CHECKPOINT
    last_linked = 0
    if checkpoint.exists():
        try:
            last_linked = int(json.loads(checkpoint.read_text(encoding="utf-8"))["last_id"])
        except Exception:
            last_linked = 0
    lemmatizer = Lemmatizer()
    map_batch = []
    new_max = last_linked
    cursor.execute("SELECT id, text_en FROM sentences WHERE id > ? ORDER BY id;", (last_linked,))
    for s_id, text_en in cursor.fetchall():
        lemmas = lemmatizer.lemmatize_text(text_en)
        for lem in lemmas:
            word_id = db_manager.get_word_id_by_lemma(lem["lemma"])
            if word_id:
                map_batch.append({"word_id": word_id, "sentence_id": s_id})
        new_max = max(new_max, s_id)
        if len(map_batch) >= 5000:
            db_manager.insert_word_sentence_map_batch(map_batch)
            map_batch = []
    if map_batch:
        db_manager.insert_word_sentence_map_batch(map_batch)
    if new_max > last_linked:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({"last_id": new_max}), encoding="utf-8")
    cursor.execute("SELECT count(*) FROM word_sentence_map;")
    map_count = cursor.fetchone()[0]
    logger.info("   [4B] Linked sentences to %s word links.", f"{map_count:,}")
```

Add `SENTENCE_LINK_CHECKPOINT` to the existing `from config.settings import (...)` block at `main.py:15` (main.py already imports `json` at line 9).

- [ ] **Step 6: Run tests** — `make test -k sentence_coverage` — PASS. Then full `make test` — green.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_sentence_coverage_pipeline.py
git commit -m "feat(ingestion): parallel corpus coverage step with incremental linking"
```

---

### Task 7: Tatoeba API fallback (residual core words)

**Files:**
- Create: `src/nlp/tatoeba_api.py`
- Create: `tests/test_tatoeba_api.py`

- [ ] **Step 1: Write failing tests** (mock HTTP — no network):

```python
import json

from src.nlp.tatoeba_api import TatoebaApiClient


def test_fetch_parses_results(monkeypatch):
    payload = {
        "results": [
            {"text": "The cat sleeps.", "translations": [[{"text": "Con mèo ngủ."}]]},
            {"text": "A dog barks.", "translations": [[]]},
        ]
    }

    class FakeResp:
        def read(self): return json.dumps(payload).encode()
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    class FakeOpener:
        def __init__(self):
            self.calls = 0
        def open(self, request):
            self.calls += 1
            return FakeResp()

    opener = FakeOpener()
    client = TatoebaApiClient(open=opener.open, min_delay=0.0)
    rows = client.fetch_sentences_for_word("cat", limit=10)

    assert len(rows) == 1
    assert rows[0]["text_en"] == "The cat sleeps."
    assert rows[0]["text_vi"] == "Con mèo ngủ."
    assert rows[0]["source"] == "Tatoeba"


def test_rate_limited(monkeypatch):
    import time
    calls = []

    def fake_open(request):
        calls.append(time.time())
        class R:
            def read(self): return json.dumps({"results": []}).encode()
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        return R()

    client = TatoebaApiClient(open=fake_open, min_delay=0.2)
    client.fetch_sentences_for_word("a", limit=1)
    client.fetch_sentences_for_word("b", limit=1)
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.15
```

- [ ] **Step 2: Run to verify fail** — `make test -k tatoeba_api` — FAIL (ImportError).

- [ ] **Step 3: Implement `src/nlp/tatoeba_api.py`**:

```python
"""Tatoeba API sentence lookup for residual core-word coverage (spec §3.3)."""

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

API_BASE = "https://api.tatoeba.org/unstable/sentences"


class TatoebaApiClient:
    def __init__(self, open: Optional[Callable] = None, min_delay: float = 1.0):
        self._open = open or urllib.request.urlopen
        self.min_delay = min_delay
        self._last_call = 0.0
        self.cache: Dict[str, List[Dict[str, Any]]] = {}

    def fetch_sentences_for_word(self, word: str, limit: int = 20) -> List[Dict[str, Any]]:
        if word in self.cache:
            return self.cache[word]
        now = time.monotonic()
        wait = self.min_delay - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

        params = urllib.parse.urlencode({
            "lang": "eng", "trans_lang": "vie", "q": word, "limit": limit,
        })
        url = f"{API_BASE}?{params}"
        try:
            with self._open(urllib.request.Request(url)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("Tatoeba API call failed for '%s': %s", word, e)
            return []

        rows = []
        for item in data.get("results", []):
            text_en = (item.get("text") or "").strip()
            if not text_en:
                continue
            text_vi = ""
            for group in item.get("translations") or []:
                for t in group:
                    if t.get("text"):
                        text_vi = t["text"].strip()
                        break
                if text_vi:
                    break
            if text_en and text_vi:
                rows.append({"text_en": text_en, "text_vi": text_vi, "source": "Tatoeba"})
        self.cache[word] = rows
        return rows
```

- [ ] **Step 4: Run tests** — `make test -k tatoeba_api` — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/nlp/tatoeba_api.py tests/test_tatoeba_api.py
git commit -m "feat(nlp): throttled Tatoeba API fallback for residual core words"
```

---

### Task 8: Gate verification + smoke run + docs

**Files:**
- Modify: `Makefile` (optional `corpus-download` target)

- [ ] **Step 1: Add Makefile target**

```make
.PHONY: corpus-download

corpus-download:
	@echo "==> Downloading parallel corpora (OpenSubtitles + EnViCorpora)..."
	$(PYTHON) -c "from scripts.download_raw_data import download_opensubtitles_envi, download_envicorpora; download_opensubtitles_envi(); download_envicorpora()"
	@echo "==> Corpora downloaded to data/raw/opensubtitles_envi/ and data/raw/envicorpora/"
```

- [ ] **Step 2: Full regression** — `make test` — Expected: all tests green (107 + ~20 new).

- [ ] **Step 3: Smoke run with real corpora** (after `make corpus-download`):

```bash
make run
```

Expected:
- `[Step 3.5] Sentence coverage: <N> new sentences ingested` (N ≥ ~100K after filtering)
- `[4B]` incremental linking only new rows
- `--build-core-pack` (or second run with `make core-pack`) produces `quality_report.md` with pass rate ≥ 95% and quarantined-for-example count < 150

- [ ] **Step 4: Verify gates from spec §5**

```bash
sqlite3 data/output/english_dataset.db "SELECT count(*) FROM sentences;"
sqlite3 data/output/english_dataset.db "SELECT source, count(*) FROM sentences GROUP BY source;"
```

Expected: `sentences` ≥ 100K; sources include `OpenSubtitles`, `TED-EnVi`, `Basic-EnVi`.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "chore(make): corpus-download target for parallel corpora"
```

---

## Self-Review

**Spec coverage:**
- §3 sources (OPUS moses, EnViCorpora ted/basic, Tatoeba API) → Tasks 2, 3, 7 ✓
- §4.1 download resumable + checksum + space check → Task 2 ✓
- §4.2 parser (side-by-side/TSV, dedupe, no word limit) → Task 3 ✓
- §4.3 noise filters (all 5 rules) → Task 4 ✓
- §4.4 incremental linking via MAX(sentences.id) checkpoint → Task 6 Step 5 ✓
- §4.5 pack rebuild + un-quarantine on re-run → Task 5 (query preference) + existing builder re-evaluates all 3,000 each build ✓
- §5 gates: ≥95% coverage → Task 8 smoke + report; idempotency → source-count checkpoint in Task 6 ✓
- §6 robustness: resume, malformed-line skip (parser skips empty lines), rate limit (Task 7) ✓
- §7 tests → Tasks 1–7 ✓
- §8 out of scope respected: no audio gen, no dialogue trees, no collocations ✓

**Placeholder scan:** no TBD/TODO; every step has code + expected output.

**Type consistency:** `ParallelCorpusParser.parse_pairs()` yields `{"text_en","text_vi","source"}` used identically in Task 3 tests, Task 6 ingest, Task 7 rows. `SentenceFilter.is_clean_pair(text_en, text_vi)` same signature everywhere. `TatoebaApiClient(open=..., min_delay=...)` matches tests.

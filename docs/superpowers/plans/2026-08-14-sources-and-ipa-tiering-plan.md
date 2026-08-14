# Missing Data Sources & Multi-Tier IPA Engine Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Oxford 3000/5000 downloader, multi-tier IPA phonetic mapping (`_ipa_cache` -> Kaikki -> CMU Dict -> g2p-en), and integrate Oxford 3000 headword validation into `CoreSelector` and `quality_report.md`.

**Architecture:** `download_raw_data.py` downloads Oxford 3000 and NLTK corpora (WordNet, CMUDict); `IPAMapper` resolves word pronunciations through a 4-tier hierarchy with persistent DuckDB `_ipa_cache` storage; `CoreSelector` and `CoreExporter` validate and report both NGSL and Oxford 3000 core list overlap.

**Tech Stack:** Python 3.14, NLTK (CMU Pronouncing Dict), g2p-en, DuckDB, SQLite3, PyTest.

**Spec:** `docs/superpowers/specs/2026-08-14-sources-and-ipa-tiering-design.md`

## Global Constraints

- Python version: Python 3.14 (.venv)
- Use standard paths: `config.settings.OXFORD_3000_PATH`, `config.settings.RAW_DATA_DIR`
- Multi-tier resolution: Tier 0 (_ipa_cache) -> Tier 1 (Kaikki) -> Tier 2 (CMU Dict) -> Tier 3 (g2p-en)
- Clean architecture with zero regressions on Phase 1 tests
- Strict adherence to TDD: Test -> Fail -> Implement -> Pass -> Commit

---

### Task 1: Oxford 3000 Downloader & Setting Configurations

**Files:**
- Modify: `config/settings.py`
- Modify: `scripts/download_raw_data.py`
- Create: `tests/test_ingestion/test_download_sources.py`

**Interfaces:**
- Consumes: `urllib.request`, `nltk.download`, `config.settings.OXFORD_3000_PATH`
- Produces: `download_oxford_3000() -> Path`, `download_nltk_corpora() -> None`

- [ ] **Step 1: Write the failing tests in `tests/test_ingestion/test_download_sources.py`**

```python
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
from scripts.download_raw_data import download_oxford_3000, download_nltk_corpora, load_oxford_words


def test_load_oxford_words_parsing():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        tmp.write("abandon\nability\nable\nabout\nabove\n")
        tmp_path = Path(tmp.name)

    try:
        words = load_oxford_words(tmp_path)
        assert len(words) == 5
        assert "abandon" in words
        assert "able" in words
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_download_oxford_3000_creates_file(tmp_path):
    dest_path = tmp_path / "oxford_3000.txt"
    with patch("scripts.download_raw_data.OXFORD_3000_PATH", dest_path):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"apple\nbanana\ncherry\n"
            mock_urlopen.return_value.__enter__.return_value.status = 200
            res_path = download_oxford_3000(dest_path=dest_path)
            assert res_path.exists()
            assert "apple" in res_path.read_text(encoding="utf-8")


def test_download_nltk_corpora_calls():
    with patch("nltk.download") as mock_nltk_download:
        download_nltk_corpora()
        assert mock_nltk_download.call_count >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingestion/test_download_sources.py -v`
Expected: FAIL

- [ ] **Step 3: Update `config/settings.py` and `scripts/download_raw_data.py`**

Add `OXFORD_3000_PATH = RAW_DATA_DIR / "oxford_3000.txt"` in `config/settings.py`.

In `scripts/download_raw_data.py`:
```python
URL_OXFORD_3000 = "https://raw.githubusercontent.com/open-dictionary/oxford-3000-5000/main/oxford3000.txt"

def load_oxford_words(path: Path) -> set:
    if not path.exists():
        return set()
    words = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            word = line.strip().lower()
            if word and not word.startswith("#"):
                words.add(word)
    return words

def download_oxford_3000(dest_path: Optional[Path] = None) -> Path:
    target = dest_path or OXFORD_3000_PATH
    if not target.exists() or target.stat().st_size == 0:
        logger.info("Downloading Oxford 3000 vocabulary list...")
        try:
            download_file(URL_OXFORD_3000, target)
        except Exception as e:
            logger.warning("Could not download Oxford 3000 from URL (%s); writing fallback list", e)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Basic fallback headwords
            target.write_text("the\nbe\nto\nof\nand\na\nin\nthat\nhave\ni\nit\nfor\nnot\non\nwith\nhe\nas\nyou\ndo\nat\n", encoding="utf-8")
    return target

def download_nltk_corpora() -> None:
    logger.info("Checking and downloading NLTK corpora (wordnet, cmudict)...")
    import nltk
    for pkg in ["wordnet", "cmudict"]:
        try:
            nltk.download(pkg, quiet=True)
        except Exception as e:
            logger.warning("Failed downloading NLTK package '%s': %s", pkg, e)
```

And update `download_all_raw_data()` to call `download_oxford_3000()` and `download_nltk_corpora()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingestion/test_download_sources.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py scripts/download_raw_data.py tests/test_ingestion/test_download_sources.py
git commit -m "feat(ingestion): add Oxford 3000 downloader and NLTK corpora download helper"
```

---

### Task 2: Multi-Tier `IPAMapper` with DuckDB Cache & CMU Pronouncing Dict

**Files:**
- Modify: `src/media/ipa_mapper.py`
- Create: `tests/test_media/test_ipa_mapper.py`

**Interfaces:**
- Consumes: `DuckDBManager`, `nltk.corpus.cmudict`, `g2p_en.G2p`
- Produces: `IPAMapper.get_ipa(word, existing_ipa_uk=None, existing_ipa_us=None) -> Tuple[str, str]` and `IPAMapper.get_ipa_string(word, existing_ipa=None) -> str`

- [ ] **Step 1: Write the failing tests in `tests/test_media/test_ipa_mapper.py`**

```python
from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.media.ipa_mapper import IPAMapper


def test_ipa_mapper_tier_hierarchy():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        mapper = IPAMapper(db_mgr=db_mgr)

        # 1. Tier 1: Existing Kaikki IPA
        uk, us = mapper.get_ipa("water", existing_ipa_uk="/ˈwɔː.tər/", existing_ipa_us="/ˈwɑː.tɚ/")
        assert uk == "/ˈwɔː.tər/"
        assert us == "/ˈwɑː.tɚ/"

        # Check that it was saved into DuckDB _ipa_cache
        cached = db_mgr.lookup_ipa("water")
        assert cached is not None
        assert cached["ipa_uk"] == "/ˈwɔː.tər/"

        # 2. Tier 0: Cache Hit
        uk_c, us_c = mapper.get_ipa("water")
        assert uk_c == "/ˈwɔː.tər/"

        # 3. Tier 2: CMU Dict Lookup (e.g. "phone")
        uk_phone, us_phone = mapper.get_ipa("phone")
        assert uk_phone is not None and "f" in uk_phone
        assert us_phone is not None and "f" in us_phone

        # 4. Tier 3: G2P Fallback for unknown word
        uk_novel, us_novel = mapper.get_ipa("chatgptification")
        assert uk_novel is not None and len(uk_novel) > 0


def test_ipa_mapper_backward_compatibility():
    mapper = IPAMapper()
    ipa_str = mapper.get_ipa_string("hello", existing_ipa="/həˈloʊ/")
    assert ipa_str == "/həˈloʊ/"

    ipa_auto = mapper.get_ipa_string("banana")
    assert len(ipa_auto) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_media/test_ipa_mapper.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Multi-Tier `IPAMapper` in `src/media/ipa_mapper.py`**

```python
"""
Multi-Tier Phonetic and IPA Mapper for English Dataset System Engine.

Resolution Hierarchy:
1. Tier 0: DuckDB `_ipa_cache` lookup
2. Tier 1: Existing Kaikki Wiktionary IPA
3. Tier 2: NLTK CMU Pronouncing Dictionary (ARPAbet -> IPA)
4. Tier 3: g2p-en Neural Grapheme-to-Phoneme model
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import g2p_en
import nltk

try:
    nltk.data.find("corpora/cmudict.zip")
except LookupError:
    try:
        nltk.download("cmudict", quiet=True)
    except Exception:
        pass

from nltk.corpus import cmudict
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class IPAMapper:
    """Provides multi-tier phonetic transcriptions for English vocabulary."""

    ARPABET_TO_IPA = {
        "AA": "ɑ", "AA0": "ɑ", "AA1": "ˈɑ", "AA2": "ˌɑ",
        "AE": "æ", "AE0": "æ", "AE1": "ˈæ", "AE2": "ˌæ",
        "AH": "ʌ", "AH0": "ə", "AH1": "ˈʌ", "AH2": "ˌʌ",
        "AO": "ɔ", "AO0": "ɔ", "AO1": "ˈɔ", "AO2": "ˌɔ",
        "AW": "aʊ", "AW0": "aʊ", "AW1": "ˈaʊ", "AW2": "ˌaʊ",
        "AY": "aɪ", "AY0": "aɪ", "AY1": "ˈaɪ", "AY2": "ˌaɪ",
        "B": "b", "CH": "tʃ", "D": "d", "DH": "ð",
        "EH": "ɛ", "EH0": "ɛ", "EH1": "ˈɛ", "EH2": "ˌɛ",
        "ER": "ɜr", "ER0": "ər", "ER1": "ˈɜr", "ER2": "ˌər",
        "EY": "eɪ", "EY0": "eɪ", "EY1": "ˈeɪ", "EY2": "ˌeɪ",
        "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IH0": "ɪ", "IH1": "ˈɪ", "IH2": "ˌɪ",
        "IY": "i", "IY0": "i", "IY1": "ˈi", "IY2": "ˌi",
        "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
        "OW": "oʊ", "OW0": "oʊ", "OW1": "ˈoʊ", "OW2": "ˌoʊ",
        "OY": "ɔɪ", "OY0": "ɔɪ", "OY1": "ˈɔɪ", "OY2": "ˌɔɪ",
        "P": "p", "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ",
        "UH": "ʊ", "UH0": "ʊ", "UH1": "ˈʊ", "UH2": "ˌʊ",
        "UW": "u", "UW0": "u", "UW1": "ˈu", "UW2": "ˌu",
        "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ"
    }

    def __init__(self, db_mgr: Optional[DuckDBManager] = None):
        self.db_mgr = db_mgr
        self._cmudict = None
        self._g2p = None

    def _get_cmudict(self):
        if self._cmudict is None:
            try:
                self._cmudict = cmudict.dict()
            except Exception as e:
                logger.warning("Could not load NLTK cmudict: %s", e)
                self._cmudict = {}
        return self._cmudict

    def _get_g2p(self):
        if self._g2p is None:
            self._g2p = g2p_en.G2p()
        return self._g2p

    def _arpabet_to_ipa(self, phonemes: List[str]) -> str:
        ipa_parts = []
        for p in phonemes:
            p_clean = p.strip().upper()
            if p_clean in self.ARPABET_TO_IPA:
                ipa_parts.append(self.ARPABET_TO_IPA[p_clean])
            elif p.strip():
                ipa_parts.append(p.strip())
        return "/" + "".join(ipa_parts) + "/"

    def get_ipa(
        self,
        word: str,
        existing_ipa_uk: Optional[str] = None,
        existing_ipa_us: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        word_clean = (word or "").strip().lower()
        if not word_clean:
            return None, None

        # Tier 0: Cache lookup in DuckDB
        if self.db_mgr:
            cached = self.db_mgr.lookup_ipa(word_clean)
            if cached and (cached.get("ipa_uk") or cached.get("ipa_us")):
                return cached.get("ipa_uk"), cached.get("ipa_us")

        # Tier 1: Existing Kaikki IPA
        uk = existing_ipa_uk.strip() if existing_ipa_uk and existing_ipa_uk.strip() else None
        us = existing_ipa_us.strip() if existing_ipa_us and existing_ipa_us.strip() else None

        if uk or us:
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=uk, ipa_us=us or uk, source="kaikki")
            return uk or us, us or uk

        # Tier 2: CMU Pronouncing Dict lookup
        cmu = self._get_cmudict()
        if word_clean in cmu:
            phonemes = cmu[word_clean][0]
            ipa_val = self._arpabet_to_ipa(phonemes)
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=ipa_val, ipa_us=ipa_val, source="cmudict")
            return ipa_val, ipa_val

        # Tier 3: g2p-en Neural Model fallback
        try:
            g2p = self._get_g2p()
            phonemes = g2p(word_clean)
            ipa_val = self._arpabet_to_ipa(phonemes)
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=ipa_val, ipa_us=ipa_val, source="g2p-en")
            return ipa_val, ipa_val
        except Exception as e:
            logger.warning("G2P conversion failed for '%s': %s", word_clean, e)
            fallback = f"/{word_clean}/"
            return fallback, fallback

    def get_ipa_string(self, word: str, existing_ipa: Optional[str] = None) -> str:
        """Backward-compatible helper returning a single IPA string."""
        if existing_ipa and existing_ipa.strip():
            return existing_ipa.strip()
        uk, us = self.get_ipa(word, existing_ipa_us=existing_ipa)
        return us or uk or f"/{word}/"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_media/test_ipa_mapper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/media/ipa_mapper.py tests/test_media/test_ipa_mapper.py
git commit -m "feat(media): implement multi-tier IPAMapper with DuckDB cache, CMUDict, and g2p-en"
```

---

### Task 3: Oxford 3000 Validation in `CoreSelector` & Audit Reporting in `CoreExporter`

**Files:**
- Modify: `src/export/core_selector.py`
- Modify: `src/export/core_exporter.py`
- Modify: `src/pipeline/steps/export_core3000.py`
- Modify: `tests/test_export/test_core_selector.py`
- Modify: `tests/test_export/test_core_exporter.py`

**Interfaces:**
- Consumes: `SelectedWord.in_oxford: bool`, `CoreSelector.select_core_words(..., oxford_path=None)`, `CoreExporter.export_core_bundle(..., oxford_path=None)`
- Produces: Dual NGSL & Oxford 3000 overlap statistics in `quality_report.md`.

- [ ] **Step 1: Write test additions in `tests/test_export/test_core_selector.py` and `tests/test_export/test_core_exporter.py`**

In `tests/test_export/test_core_selector.py`:
```python
def test_core_selector_oxford_overlap(tmp_path):
    oxford_file = tmp_path / "oxford_3000.txt"
    oxford_file.write_text("water\napple\n", encoding="utf-8")

    db_path = tmp_path / "staging.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    db_mgr.insert_batch_fast("words", [
        {"id": 1, "lemma": "water", "pos": "noun", "frequency_rank": 50, "source": "kaikki"},
        {"id": 2, "lemma": "rocket", "pos": "noun", "frequency_rank": 100, "source": "kaikki"},
    ])

    selector = CoreSelector()
    selected = selector.select_core_words(db_mgr, limit=10, oxford_path=oxford_file)

    water_w = next(w for w in selected if w.lemma == "water")
    rocket_w = next(w for w in selected if w.lemma == "rocket")

    assert water_w.in_oxford is True
    assert rocket_w.in_oxford is False
```

- [ ] **Step 2: Update `src/export/core_selector.py`, `src/export/core_exporter.py`, and `src/pipeline/steps/export_core3000.py`**

In `src/export/core_selector.py`:
- Add `in_oxford: bool = False` to `SelectedWord`.
- In `select_core_words(self, db_mgr, limit=3000, ngsl_path=None, oxford_path=None)`:
  - Load `oxford_words` from `oxford_path`.
  - Check `in_oxford = clean_lemma in oxford_words`.

In `src/export/core_exporter.py`:
- Accept `oxford_path: Optional[Path] = None` in `export_core_bundle()`.
- In `write_quality_report()`:
  - Calculate `oxford_count = sum(1 for w in selected_words if getattr(w, "in_oxford", False))`.
  - Add Oxford 3000 Overlap metrics into the markdown header and summary table.

In `src/pipeline/steps/export_core3000.py`:
- Pass `oxford_path=settings.OXFORD_3000_PATH` into `exporter.export_core_bundle()`.

- [ ] **Step 3: Run all export and media tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_export/ tests/test_media/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/export/core_selector.py src/export/core_exporter.py src/pipeline/steps/export_core3000.py tests/test_export/
git commit -m "feat(export): integrate Oxford 3000 validation into CoreSelector and quality_report.md"
```

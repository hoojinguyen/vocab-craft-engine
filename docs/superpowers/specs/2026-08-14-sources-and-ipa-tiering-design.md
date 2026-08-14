# Missing Data Sources & Multi-Tier IPA Engine (Phase 2)

## 1. Executive Summary

This specification defines the implementation of missing dataset sources and phonetic pronunciation enhancements for the Pipeline V2 engine:
1. **Oxford 3000/5000 Integration**: Automated downloader for the Oxford 3000 vocabulary list, integration into `CoreSelector`, and inclusion of Oxford 3000 overlap metrics in `quality_report.md`.
2. **Multi-Tier IPA Engine (`IPAMapper`)**: Multi-tier phonetic transcription engine integrating:
   - Tier 0: DuckDB `_ipa_cache` lookup (instant ~1µs retrieval).
   - Tier 1: Kaikki Wiktionary UK/US pronunciations.
   - Tier 2: NLTK CMU Pronouncing Dictionary (`nltk.corpus.cmudict`) with ARPAbet-to-IPA phoneme mapping.
   - Tier 3: `g2p-en` Grapheme-to-Phoneme model fallback.
   - Cache persistence into DuckDB's `_ipa_cache` table.
3. **Automated Raw Data Downloads**: Adding Oxford 3000, WordNet, and CMUDict NLTK packages into `scripts/download_raw_data.py`.

---

## 2. Architecture & Data Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Download & Storage                                                  │
│                                                                        │
│ scripts/download_raw_data.py                                           │
│ ├── download_oxford_3000() ──> data/raw/oxford_3000.txt                │
│ └── download_nltk_corpora() ──> nltk.download('cmudict', 'wordnet')   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Multi-Tier Phonetic Resolution (IPAMapper)                          │
│                                                                        │
│ Word ──> [Tier 0: DuckDB _ipa_cache] ──HIT──> Return cached IPA        │
│                     │ MISS                                             │
│                     ▼                                                  │
│          [Tier 1: Kaikki UK/US IPA] ──HIT──> Cache & Return            │
│                     │ MISS                                             │
│                     ▼                                                  │
│          [Tier 2: NLTK CMU Dict]    ──HIT──> Convert ARPAbet ➔ IPA     │
│                     │                        Cache & Return            │
│                     ▼ MISS                                             │
│          [Tier 3: g2p_en G2P]       ───────> Convert G2P ➔ IPA         │
│                                              Cache & Return            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Core Word List Overlap & Quality Reporting                          │
│                                                                        │
│ • CoreSelector: in_oxford flag calculation (overlap with Oxford 3000)  │
│ • CoreExporter: Dual NGSL & Oxford 3000 overlap audit in quality report│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Details

### 3.1 Downloader & Settings Configuration
- **`config/settings.py`**:
  - Add `OXFORD_3000_PATH = RAW_DATA_DIR / "oxford_3000.txt"`
- **`scripts/download_raw_data.py`**:
  - `download_oxford_3000()`: Downloads Oxford 3000 list from reliable open mirror with local fallback.
  - `download_nltk_corpora()`: Ensures `wordnet` and `cmudict` are present via `nltk.download()`.
  - Wire into `download_all_raw_data()`.

### 3.2 Multi-Tier `IPAMapper` (`src/media/ipa_mapper.py` / `src/enrichment/ipa_mapper.py`)
- **ARPAbet to IPA Translation Table**:
  - Maps stress-marked ARPAbet symbols (e.g. `AA0`, `AA1`, `AA2`, `T`, `CH`, `DH`, `ER1`, etc.) to standard IPA characters.
- **Resolution Pipeline**:
```python
class IPAMapper:
    def __init__(self, db_mgr: Optional[DuckDBManager] = None):
        self.db_mgr = db_mgr
        self._cmudict = None
        self._g2p = None

    def get_ipa(
        self,
        word: str,
        existing_ipa_uk: Optional[str] = None,
        existing_ipa_us: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Returns (ipa_uk, ipa_us) using the 4-tier hierarchy:
        1. DuckDB _ipa_cache lookup
        2. existing_ipa (Kaikki)
        3. CMU Pronouncing Dictionary
        4. g2p-en phonetic model fallback
        """
```

### 3.3 Core Selection & Overlap Reporting
- **`src/export/core_selector.py`**:
  - Update `SelectedWord` to include `in_oxford: bool = False`.
  - Update `select_core_words` to accept `oxford_path: Optional[Path] = None`.
  - Parse `oxford_3000.txt` and assign `in_oxford = clean_lemma in oxford_words`.
- **`src/export/core_exporter.py`**:
  - Include Oxford 3000 metrics in `write_quality_report()`:
    - `Total Oxford 3000 Overlap: X (Y%)`
    - Summary table comparing NGSL coverage vs Oxford 3000 coverage.
- **`src/pipeline/steps/export_core3000.py`**:
  - Pass `oxford_path=settings.OXFORD_3000_PATH` to `CoreExporter`.

---

## 4. Verification & Testing Strategy

1. **`tests/test_media/test_ipa_mapper.py`**:
   - Test cache hit from DuckDB `_ipa_cache`.
   - Test CMU Dict phonetic translation for standard English vocabulary.
   - Test `g2p-en` fallback for out-of-vocabulary / novel terms.
   - Test automatic caching of newly computed pronunciations into `_ipa_cache`.
2. **`tests/test_export/test_core_selector.py`**:
   - Test `in_oxford` flag computation with test fixture files.
3. **`tests/test_export/test_core_exporter.py`**:
   - Test `quality_report.md` generation includes Oxford 3000 statistics.
4. **`tests/test_pipeline/test_export_core3000_step.py`**:
   - Test end-to-end execution of `ExportCore3000Step` with Oxford 3000 path provided.

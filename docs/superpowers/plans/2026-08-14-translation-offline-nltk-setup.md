# Translation Offline Setup, NLTK Automation & Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate local workspace NLTK downloading, offline Argos English-Vietnamese model installation, and integrate detailed Translation Telemetry & Quota Accounting into `HybridTranslator`.

**Architecture:** Python script utilities in `scripts/download_raw_data.py` configuring workspace data paths, combined with telemetry counters inside `src/enrichment/translation.py` reporting metrics to both logs and TUI.

**Tech Stack:** Python 3.11+, NLTK, Argos Translate, Deep Translator, DuckDB, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-translation-offline-nltk-setup-design.md`

## Global Constraints

- Must never attempt downloading to `~/nltk_data` (always specify `download_dir`).
- Offline Argos Translate installation must handle network errors gracefully without crashing the downloader.
- Translation stats must accurately track cache hits, offline engine, fallback engine, and rejected items.
- Maintain 100% test pass rate across the full pytest suite.

---

### Task 1: Local NLTK & Argos Offline Downloader

**Files:**
- Modify: `scripts/download_raw_data.py`
- Test: `tests/test_download_script.py`

**Interfaces:**
- Consumes: `NLTK_DATA_DIR` from `config.settings`
- Produces:
  - `download_nltk_corpora(target_dir: Optional[Path] = None) -> List[str]`
  - `install_argos_models() -> bool`

- [ ] **Step 1: Write failing unit test for local NLTK & Argos downloader**

Update `tests/test_download_script.py`:
```python
from pathlib import Path
from unittest.mock import patch, MagicMock
from scripts.download_raw_data import download_nltk_corpora, install_argos_models


def test_download_nltk_corpora_uses_local_target_dir(tmp_path):
    with patch("nltk.download") as mock_download:
        mock_download.return_value = True
        download_nltk_corpora(target_dir=tmp_path)
        assert mock_download.call_count >= 4
        # Verify download_dir was passed
        for call in mock_download.call_args_list:
            assert "download_dir" in call.kwargs
            assert call.kwargs["download_dir"] == str(tmp_path)


def test_install_argos_models_already_installed():
    with patch("argostranslate.translate.get_installed_languages") as mock_get_lang:
        mock_en = MagicMock()
        mock_en.code = "en"
        mock_vi = MagicMock()
        mock_vi.code = "vi"
        mock_translation = MagicMock()
        mock_translation.to_lang = mock_vi
        mock_en.get_translations.return_value = [mock_translation]
        mock_get_lang.return_value = [mock_en, mock_vi]

        res = install_argos_models()
        assert res is True
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_download_script.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `download_nltk_corpora` and `install_argos_models` in `scripts/download_raw_data.py`**

In `scripts/download_raw_data.py`:
```python
def download_nltk_corpora(target_dir: Path | None = None) -> list[str]:
    """Checks and downloads NLTK corpora directly into local workspace directory."""
    from config.settings import NLTK_DATA_DIR, VENV_NLTK_DATA_DIR

    dest = target_dir or (VENV_NLTK_DATA_DIR if VENV_NLTK_DATA_DIR.exists() else NLTK_DATA_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading NLTK corpora to %s...", dest)

    packages = [
        "wordnet",
        "cmudict",
        "averaged_perceptron_tagger_eng",
        "omw-1.4",
        "punkt_tab",
    ]
    downloaded = []
    try:
        import nltk

        for pkg in packages:
            try:
                nltk.download(pkg, download_dir=str(dest), quiet=True)
                downloaded.append(pkg)
            except Exception as e:
                logger.warning("Failed downloading NLTK package '%s': %s", pkg, e)
    except ImportError:
        logger.warning("NLTK not installed; skipping NLTK download")
    return downloaded


def install_argos_models() -> bool:
    """Checks and installs Argos Translate English to Vietnamese offline package."""
    try:
        import argostranslate.package
        import argostranslate.translate

        installed_languages = argostranslate.translate.get_installed_languages()
        from_lang = next((lang for lang in installed_languages if lang.code == "en"), None)
        to_lang = next((lang for lang in installed_languages if lang.code == "vi"), None)

        if from_lang and to_lang:
            translations = from_lang.get_translations(to_lang)
            if translations:
                logger.info("Argos Translate en->vi translation package is already installed.")
                return True

        logger.info("Updating Argos Translate package index...")
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            (p for p in available_packages if p.from_code == "en" and p.to_code == "vi"),
            None,
        )

        if package_to_install:
            logger.info("Installing Argos Translate en->vi package...")
            download_path = package_to_install.download()
            argostranslate.package.install_from_path(download_path)
            logger.info("Successfully installed Argos Translate en->vi model!")
            return True
        else:
            logger.warning("Argos Translate en->vi package not found in index.")
            return False
    except Exception as e:
        logger.warning("Could not auto-install Argos Translate offline models: %s", e)
        return False
```

Update `download_all_raw_data()` to call `download_nltk_corpora()` and `install_argos_models()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_download_script.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/download_raw_data.py tests/test_download_script.py
git commit -m "feat(download): automate local workspace NLTK downloading and Argos en-vi model setup"
```

---

### Task 2: Translation Telemetry & Quota Accounting in `HybridTranslator`

**Files:**
- Modify: `src/enrichment/translation.py`
- Modify: `src/pipeline/steps/enrich_translation.py`
- Test: `tests/test_enrichment/test_translation_stats.py`

**Interfaces:**
- Consumes: None
- Produces:
  - `TranslationStats(cache_hits, argos_translated, google_translated, validation_rejected, total_requested)`
  - `HybridTranslator.stats` and `HybridTranslator.get_summary()`
  - Logged breakdown metrics in `EnrichTranslationStep`

- [ ] **Step 1: Write failing unit test for TranslationStats**

Create `tests/test_enrichment/test_translation_stats.py`:
```python
from unittest.mock import MagicMock
from src.enrichment.translation import HybridTranslator, TranslationStats
from src.db.duckdb_manager import DuckDBManager


def test_translation_stats_accounting(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "test_stats.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)
    assert isinstance(translator.stats, TranslationStats)
    assert translator.stats.total_requested == 0

    # Mock cached translation
    db_mgr.save_translation("hello", "xin chào", "test")
    res = translator.translate_text("hello")
    assert res == "xin chào"
    assert translator.stats.cache_hits == 1
    assert translator.stats.total_requested == 1

    summary = translator.get_summary()
    assert summary["cache_hits"] == 1
    assert summary["total_requested"] == 1
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/pytest tests/test_enrichment/test_translation_stats.py -v`
Expected: FAIL

- [ ] **Step 3: Implement TranslationStats in `src/enrichment/translation.py` and update step**

In `src/enrichment/translation.py`:
- Add `TranslationStats` dataclass.
- Update `translate_text`:
  - `self.stats.total_requested += 1`
  - On cache hit -> `self.stats.cache_hits += 1`
  - On Argos success -> `self.stats.argos_translated += 1`
  - On Google fallback -> `self.stats.google_translated += 1`
  - If validation fails -> `self.stats.validation_rejected += 1`
- Add `get_summary() -> Dict[str, Any]` method.

In `src/pipeline/steps/enrich_translation.py`:
- Log the translation summary breakdown upon step completion:
  ```python
  summary = translator.get_summary()
  logger.info(
      "Translation Complete: %d defs, %d phrases (Total: %d) | Cache Hits: %d (%.1f%%) | Argos: %d | Google: %d | Rejects: %d",
      count_defs, count_phrases, total,
      summary["cache_hits"], summary["cache_ratio_pct"],
      summary["argos_translated"], summary["google_translated"],
      summary["validation_rejected"],
  )
  ```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_enrichment/test_translation_stats.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify 100% pass**

Run: `.venv/bin/pytest -v`
Expected: 267+ passed, 0 failed

- [ ] **Step 6: Commit**

```bash
git add src/enrichment/translation.py src/pipeline/steps/enrich_translation.py tests/test_enrichment/test_translation_stats.py
git commit -m "feat(enrichment): add TranslationStats accounting and telemetry breakdown to HybridTranslator"
```

---

## Verification Plan

### Automated Tests
```bash
pytest tests/test_download_script.py -v
pytest tests/test_enrichment/test_translation_stats.py -v
pytest -v
```

### Manual Verification
1. Run `python scripts/download_raw_data.py` (or test with dry-run) to verify NLTK corpora are downloaded without permission errors.
2. Run `python main.py --dry-run` to verify step registration and parameters.

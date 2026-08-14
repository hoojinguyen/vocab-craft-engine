from unittest.mock import MagicMock, patch
import pytest
from src.enrichment.translation import HybridTranslator, TranslationStats
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.steps.enrich_translation import EnrichTranslationStep


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
    assert summary["cache_ratio_pct"] == 100.0
    db_mgr.close()


def test_translation_stats_argos_accounting(tmp_path, monkeypatch):
    import sys
    db_mgr = DuckDBManager(tmp_path / "test_argos.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)

    mock_pkg = MagicMock()
    mock_translate_mod = MagicMock()
    mock_translate_mod.translate.return_value = "chạy nhanh"
    mock_pkg.translate = mock_translate_mod
    monkeypatch.setitem(sys.modules, "argostranslate", mock_pkg)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", mock_translate_mod)

    res = translator.translate_text("run fast")
    assert res == "chạy nhanh"
    assert translator.stats.total_requested == 1
    assert translator.stats.cache_hits == 0
    assert translator.stats.argos_translated == 1
    assert translator.stats.google_translated == 0

    db_mgr.close()


def test_translation_stats_google_fallback_accounting(tmp_path, monkeypatch):
    import sys
    db_mgr = DuckDBManager(tmp_path / "test_google.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)

    # Force Argos to fail
    monkeypatch.setitem(sys.modules, "argostranslate", None)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", None)

    mock_google_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.translate.return_value = "học tập"
    mock_google_cls.return_value = mock_instance
    monkeypatch.setattr("deep_translator.GoogleTranslator", mock_google_cls)

    res = translator.translate_text("study")
    assert res == "học tập"
    assert translator.stats.total_requested == 1
    assert translator.stats.google_translated == 1
    assert translator.stats.argos_translated == 0

    db_mgr.close()


def test_translation_stats_validation_rejection(tmp_path, monkeypatch):
    import sys
    db_mgr = DuckDBManager(tmp_path / "test_reject.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)

    # Mock validator returning False for engine translation
    monkeypatch.setattr(translator.validator, "validate", lambda text: False)

    mock_pkg = MagicMock()
    mock_translate_mod = MagicMock()
    mock_translate_mod.translate.return_value = "invalid text"
    mock_pkg.translate = mock_translate_mod
    monkeypatch.setitem(sys.modules, "argostranslate", mock_pkg)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", mock_translate_mod)

    mock_google_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.translate.return_value = "invalid text"
    mock_google_cls.return_value = mock_instance
    monkeypatch.setattr("deep_translator.GoogleTranslator", mock_google_cls)

    res = translator.translate_text("some words")
    assert res == "[VI] some words"
    assert translator.stats.total_requested == 1
    assert translator.stats.validation_rejected >= 1

    summary = translator.get_summary()
    assert summary["validation_rejected"] >= 1
    assert summary["total_requested"] == 1

    db_mgr.close()


def test_translation_stats_summary_empty(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "test_empty.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)
    summary = translator.get_summary()
    assert summary["total_requested"] == 0
    assert summary["cache_hits"] == 0
    assert summary["cache_ratio_pct"] == 0.0
    assert summary["argos_translated"] == 0
    assert summary["google_translated"] == 0
    assert summary["validation_rejected"] == 0

    db_mgr.close()


def test_enrich_translation_step_metrics(tmp_path):
    db_path = tmp_path / "test_step.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    db_mgr.insert_batch_fast("words", [{"lemma": "book", "pos": "noun", "source": "kaikki"}])
    conn = db_mgr.get_connection()
    word_id = conn.execute("SELECT id FROM words WHERE lemma = 'book'").fetchone()[0]
    db_mgr.insert_batch_fast("definitions", [
        {"word_id": word_id, "definition_en": "a written work", "definition_vi": None, "source": "kaikki"}
    ])
    db_mgr.save_translation("a written work", "một tác phẩm viết", "manual")

    ctx = PipelineContext(db_manager=db_mgr)
    step = EnrichTranslationStep()
    result = step.run(ctx)

    assert result.status.value == "SUCCESS"
    assert result.items_processed >= 1
    assert "cache_hits" in result.metrics
    db_mgr.close()


def test_translation_stats_batch_accounting(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "test_batch.duckdb")
    db_mgr.init_schema()

    # Pre-populate cache with one item
    db_mgr.save_translation("apple", "quả táo", "manual")

    translator = HybridTranslator(db_mgr)
    # Batch with 1 cached, 1 missing, and empty strings
    res = translator.translate_texts_batch(["apple", "banana", "", "   "])
    assert res["apple"] == "quả táo"
    assert "banana" in res
    assert translator.stats.total_requested == 2
    assert translator.stats.cache_hits == 1

    summary = translator.get_summary()
    assert summary["total_requested"] == 2
    assert summary["cache_hits"] == 1
    assert summary["cache_ratio_pct"] == 50.0

    db_mgr.close()


def test_translation_stats_empty_text(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "test_empty_text.duckdb")
    db_mgr.init_schema()

    translator = HybridTranslator(db_mgr)
    assert translator.translate_text("") == ""
    assert translator.translate_text("   ") == ""
    assert translator.stats.total_requested == 0

    db_mgr.close()

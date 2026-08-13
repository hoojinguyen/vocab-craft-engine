import pytest
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator
from src.enrichment.translation import HybridTranslator
from src.pipeline.steps.enrich_translation import EnrichTranslationStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb"}])
    mgr.insert_batch("definitions", [{"word_id": 1, "definition_en": "to move fast"}])
    yield mgr
    mgr.close()


def test_vi_validator():
    validator = VietnameseValidator()
    assert validator.validate("chạy nhanh") is True
    assert validator.validate("") is False


def test_hybrid_translator_cached_or_mock(db_mgr):
    translator = HybridTranslator(db_mgr)
    translated = translator.translate_text("hello")
    assert isinstance(translated, str)
    assert len(translated) > 0

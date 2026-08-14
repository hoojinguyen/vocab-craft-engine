import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator
from src.enrichment.translation import HybridTranslator
from src.pipeline.steps.enrich_translation import EnrichTranslationStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_vi_validator():
    validator = VietnameseValidator()
    assert validator.validate("chạy nhanh") is True
    assert validator.validate("Học tiếng Anh mỗi ngày") is True
    assert validator.validate("") is False
    assert validator.validate(None) is False


def test_hybrid_translator_batch_and_cache(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    conn = db_mgr.get_connection()
    word_id = conn.execute("SELECT id FROM words WHERE lemma = 'run'").fetchone()[0]

    db_mgr.insert_batch_fast("definitions", [
        {"word_id": word_id, "definition_en": "to move swiftly on foot", "definition_vi": None, "source": "kaikki"},
        {"word_id": word_id, "definition_en": "to manage or operate", "definition_vi": None, "source": "kaikki"},
    ])

    db_mgr.insert_batch_fast("phrases", [
        {"phrase": "run away", "phrase_type": "phrasal_verb", "definition_en": "to escape", "definition_vi": None},
    ])

    # Pre-populate translation cache
    db_mgr.save_translation("to escape", "trốn thoát", translator="manual")

    translator = HybridTranslator(db_mgr)
    count_defs = translator.translate_definitions(limit=10)
    count_phrases = translator.translate_phrases(limit=10)

    assert count_defs == 2
    assert count_phrases == 1

    # Verify cached translation was used for phrase
    phrase_vi = conn.execute("SELECT definition_vi FROM phrases WHERE phrase = 'run away'").fetchone()[0]
    assert phrase_vi == "trốn thoát"

    # Verify definitions got translated
    defs_vi = conn.execute("SELECT definition_vi FROM definitions WHERE word_id = ?", [word_id]).fetchall()
    assert len(defs_vi) == 2
    assert all(d[0] is not None and len(d[0]) > 0 for d in defs_vi)


def test_enrich_translation_step():
    step = EnrichTranslationStep()
    assert step.name == "enrich_translation"
    assert "definitions" in step.produces or "definitions_vi" in str(step.produces)

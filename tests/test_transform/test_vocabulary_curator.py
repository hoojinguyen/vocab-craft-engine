import pytest
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.enrich_ipa import EnrichIPAStep
from src.transform.vocabulary_curator import VocabularyCurator, determine_cefr_level


def test_determine_cefr_level():
    oxford = {"abandon", "ability", "accept"}
    ngsl = {"the", "be", "to", "of", "and"}
    awl = {"analysis", "approach", "concept"}

    assert determine_cefr_level("the", 1, oxford, ngsl, awl) == "A1"
    assert determine_cefr_level("abandon", 2200, oxford, ngsl, awl) == "B1"
    assert determine_cefr_level("analysis", 4000, oxford, ngsl, awl) == "B2"
    assert determine_cefr_level("esoteric", 35000, oxford, ngsl, awl) == "C2"


def test_vocabulary_curator_filters_noise_and_caps(tmp_path):
    db_path = tmp_path / "test_staging.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # Insert sample test words
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "frequency_rank": 1500, "cefr_level": "B1"},
        {"id": 2, "lemma": "2,4-d", "pos": "noun", "frequency_rank": None, "cefr_level": "C2"},  # junk
        {"id": 3, "lemma": "x", "pos": "noun", "frequency_rank": None, "cefr_level": "C2"},  # single char junk
        {"id": 4, "lemma": "a", "pos": "det", "frequency_rank": 5, "cefr_level": "A1"},  # valid single char
        {"id": 5, "lemma": "hello world", "pos": "phrase", "frequency_rank": None, "cefr_level": "A1"},  # space
        {"id": 6, "lemma": "concept", "pos": "noun", "frequency_rank": 3000, "cefr_level": "B2"},
    ]
    db_mgr.insert_batch_fast("words", words)

    defs = [
        {"id": 1, "word_id": 1, "definition_en": "to leave behind", "definition_vi": "từ bỏ"},
        {"id": 2, "word_id": 2, "definition_en": "herbicide", "definition_vi": "thuốc trừ cỏ"},
        {"id": 3, "word_id": 6, "definition_en": "an abstract idea", "definition_vi": "khái niệm"},
    ]
    db_mgr.insert_batch_fast("definitions", defs)

    curator = VocabularyCurator(target_limit=10, oxford_words={"abandon"}, awl_words={"concept"})
    stats = curator.curate(db_mgr)

    assert stats["words_after"] == 3  # abandon, a, concept
    assert stats["definitions_after"] == 2  # defs for abandon and concept (def for 2,4-d purged)

    conn = db_mgr.get_connection()
    remaining_lemmas = [row[0] for row in conn.execute("SELECT lemma FROM words ORDER BY lemma").fetchall()]
    assert remaining_lemmas == ["a", "abandon", "concept"]
    db_mgr.close()


def test_enrich_ipa_step(tmp_path):
    db_path = tmp_path / "test_ipa_staging.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "ipa_uk": None, "ipa_us": None},
        {"id": 2, "lemma": "cat", "pos": "noun", "ipa_uk": None, "ipa_us": None},
    ]
    db_mgr.insert_batch_fast("words", words)

    step = EnrichIPAStep()
    ctx = PipelineContext(db_manager=db_mgr)
    res = step.run(ctx)

    assert res.status == StepStatus.SUCCESS
    assert res.items_processed == 2

    conn = db_mgr.get_connection()
    rows = conn.execute("SELECT lemma, ipa_us FROM words ORDER BY id").fetchall()
    assert rows[0][1] is not None
    assert rows[1][1] is not None
    db_mgr.close()

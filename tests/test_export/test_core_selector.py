from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_selector import CoreSelector, SelectedWord, rank_to_cefr, normalize_freq_word


def test_normalize_freq_word_contractions():
    assert normalize_freq_word("don't") == "do"
    assert normalize_freq_word("can't") == "can"
    assert normalize_freq_word("they're") == "they"
    assert normalize_freq_word("apple") == "apple"
    assert normalize_freq_word(" won't ") == "will"
    assert normalize_freq_word("") == ""
    assert normalize_freq_word(None) == ""


def test_rank_to_cefr():
    assert rank_to_cefr(200) == "A1"
    assert rank_to_cefr(500) == "A1"
    assert rank_to_cefr(501) == "A2"
    assert rank_to_cefr(1000) == "A2"
    assert rank_to_cefr(1500) == "A2"
    assert rank_to_cefr(2500) == "B1"
    assert rank_to_cefr(3500) == "B1"
    assert rank_to_cefr(5000) == "B2"
    assert rank_to_cefr(7000) == "B2"
    assert rank_to_cefr(12000) == "C1"
    assert rank_to_cefr(15000) == "C1"
    assert rank_to_cefr(20000) == "C2"
    assert rank_to_cefr(None) == "C2"
    assert rank_to_cefr(0) == "C2"
    assert rank_to_cefr(-5) == "C2"


def test_core_selector_filters_noise_and_ranks():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        words_data = [
            {"id": 1, "lemma": "the", "pos": "article", "frequency_rank": 1, "source": "kaikki"},
            {"id": 2, "lemma": "john", "pos": "name", "frequency_rank": 2, "source": "kaikki"},
            {"id": 3, "lemma": "un-", "pos": "prefix", "frequency_rank": 3, "source": "kaikki"},
            {"id": 4, "lemma": "water", "pos": "noun", "frequency_rank": 50, "source": "kaikki"},
            {"id": 5, "lemma": "run", "pos": "verb", "frequency_rank": 100, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("words", words_data)

        selector = CoreSelector()
        selected = selector.select_core_words(db_mgr, limit=3)

        assert len(selected) == 3
        lemmas = [w.lemma for w in selected]
        assert "john" not in lemmas  # name filtered out
        assert "un-" not in lemmas   # prefix filtered out
        assert "the" in lemmas
        assert "water" in lemmas
        assert "run" in lemmas

        water_entry = next(w for w in selected if w.lemma == "water")
        assert water_entry.cefr_level == "A1"


def test_core_selector_ngsl_overlap(tmp_path: Path):
    db_path = tmp_path / "staging.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    ngsl_file = tmp_path / "NGSL.csv"
    ngsl_file.write_text("the,the,\nwater,waters,\n", encoding="utf-8")

    words_data = [
        {"id": 1, "lemma": "the", "pos": "article", "frequency_rank": 1, "source": "kaikki"},
        {"id": 2, "lemma": "water", "pos": "noun", "frequency_rank": 50, "source": "kaikki"},
        {"id": 3, "lemma": "python", "pos": "noun", "frequency_rank": 6000, "source": "kaikki"},
    ]
    db_mgr.insert_batch_fast("words", words_data)

    selector = CoreSelector()
    selected = selector.select_core_words(db_mgr, limit=10, ngsl_path=ngsl_file)

    assert len(selected) == 3
    the_entry = next(w for w in selected if w.lemma == "the")
    water_entry = next(w for w in selected if w.lemma == "water")
    python_entry = next(w for w in selected if w.lemma == "python")

    assert the_entry.in_ngsl is True
    assert water_entry.in_ngsl is True
    assert python_entry.in_ngsl is False
    assert python_entry.cefr_level == "B2"


def test_core_selector_deduplication_and_limit(tmp_path: Path):
    db_path = tmp_path / "staging.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    words_data = [
        {"id": 1, "lemma": "run", "pos": "verb", "frequency_rank": 10, "source": "kaikki"},
        {"id": 2, "lemma": "run", "pos": "noun", "frequency_rank": 15, "source": "kaikki"},
        {"id": 3, "lemma": "walk", "pos": "verb", "frequency_rank": 20, "source": "kaikki"},
        {"id": 4, "lemma": "jump", "pos": "verb", "frequency_rank": 30, "source": "kaikki"},
    ]
    db_mgr.insert_batch_fast("words", words_data)

    selector = CoreSelector()
    selected = selector.select_core_words(db_mgr, limit=2)

    assert len(selected) == 2
    assert [w.lemma for w in selected] == ["run", "walk"]

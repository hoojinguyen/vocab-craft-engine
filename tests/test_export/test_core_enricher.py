from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.export.core_selector import SelectedWord
from src.export.core_enricher import CoreEnricher, QualityGateResult, EnrichmentSummary


def test_core_enricher_quality_gates():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        # Word 1: Complete (Passes all 5 gates)
        # Word 2: Missing Vietnamese Definition (Fails Gate 2)
        words_data = [
            {"id": 1, "lemma": "apple", "pos": "noun", "ipa_uk": "/ˈæp.əl/", "ipa_us": "/ˈæp.əl/", "frequency_rank": 100, "source": "kaikki"},
            {"id": 2, "lemma": "banana", "pos": "noun", "ipa_uk": "/bəˈnæn.ə/", "ipa_us": "/bəˈnæn.ə/", "frequency_rank": 200, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("words", words_data)

        defs_data = [
            {"id": 1, "word_id": 1, "definition_en": "A round red or green fruit", "definition_vi": "Quả táo", "source": "kaikki"},
            {"id": 2, "word_id": 2, "definition_en": "An elongated yellow fruit", "definition_vi": None, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("definitions", defs_data)

        sent_data = [
            {"id": 1, "text_en": "I eat an apple every day.", "text_vi": "Tôi ăn một quả táo mỗi ngày.", "source": "tatoeba"},
            {"id": 2, "text_en": "Monkeys love bananas.", "text_vi": "Khỉ thích chuối.", "source": "tatoeba"},
        ]
        db_mgr.insert_batch_fast("sentences", sent_data)

        ws_data = [
            {"word_id": 1, "sentence_id": 1},
            {"word_id": 2, "sentence_id": 2},
        ]
        db_mgr.insert_batch_fast("word_sentences", ws_data)

        topics_data = [
            {"word_id": 1, "topic": "Food & Drink", "raw_topic": "Food & Drink"},
            {"word_id": 2, "topic": "Food & Drink", "raw_topic": "Food & Drink"},
        ]
        db_mgr.insert_batch_fast("word_topics", topics_data)

        selected = [
            SelectedWord(id=1, lemma="apple", pos="noun", frequency_rank=100, cefr_level="A1", in_ngsl=True, source="kaikki"),
            SelectedWord(id=2, lemma="banana", pos="noun", frequency_rank=200, cefr_level="A1", in_ngsl=True, source="kaikki"),
        ]

        enricher = CoreEnricher()
        enriched_list, summary = enricher.validate_and_enrich(db_mgr, selected)

        assert len(enriched_list) == 2
        assert summary.total_words == 2
        assert summary.passed_all_gates == 1
        assert summary.def_en_coverage == 1.0
        assert summary.def_vi_coverage == 0.5
        assert summary.ipa_coverage == 1.0
        assert summary.sentence_coverage == 1.0
        assert summary.topic_coverage == 1.0

        apple_res = next(r for r in summary.gate_results if r.lemma == "apple")
        assert apple_res.passed_all is True

        banana_res = next(r for r in summary.gate_results if r.lemma == "banana")
        assert banana_res.passed_all is False
        assert "def_vi" in banana_res.missing_fields


def test_core_enricher_empty_and_each_gate_failure():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        enricher = CoreEnricher()
        enriched, summary = enricher.validate_and_enrich(db_mgr, [])
        assert enriched == []
        assert summary.total_words == 0
        assert summary.passed_all_gates == 0

        # Word 10: missing def_en
        # Word 20: missing ipa
        # Word 30: missing sentence
        # Word 40: missing topic
        words_data = [
            {"id": 10, "lemma": "word10", "pos": "noun", "ipa_uk": "/w10/", "ipa_us": None, "frequency_rank": 10, "source": "kaikki"},
            {"id": 20, "lemma": "word20", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 20, "source": "kaikki"},
            {"id": 30, "lemma": "word30", "pos": "noun", "ipa_uk": "/w30/", "ipa_us": None, "frequency_rank": 30, "source": "kaikki"},
            {"id": 40, "lemma": "word40", "pos": "noun", "ipa_uk": "/w40/", "ipa_us": None, "frequency_rank": 40, "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("words", words_data)

        defs_data = [
            {"id": 10, "word_id": 10, "definition_en": "sh", "definition_vi": "Nghĩa ngắn", "source": "kaikki"},  # len < 5 -> fails def_en
            {"id": 20, "word_id": 20, "definition_en": "Valid English definition", "definition_vi": "Định nghĩa tiếng Việt", "source": "kaikki"},
            {"id": 30, "word_id": 30, "definition_en": "Valid English definition", "definition_vi": "Định nghĩa tiếng Việt", "source": "kaikki"},
            {"id": 40, "word_id": 40, "definition_en": "Valid English definition", "definition_vi": "Định nghĩa tiếng Việt", "source": "kaikki"},
        ]
        db_mgr.insert_batch_fast("definitions", defs_data)

        sent_data = [
            {"id": 10, "text_en": "Sentence 10", "text_vi": "Câu 10", "source": "tatoeba"},
            {"id": 20, "text_en": "Sentence 20", "text_vi": "Câu 20", "source": "tatoeba"},
            {"id": 40, "text_en": "Sentence 40", "text_vi": "Câu 40", "source": "tatoeba"},
        ]
        db_mgr.insert_batch_fast("sentences", sent_data)

        ws_data = [
            {"word_id": 10, "sentence_id": 10},
            {"word_id": 20, "sentence_id": 20},
            {"word_id": 40, "sentence_id": 40},
        ]
        db_mgr.insert_batch_fast("word_sentences", ws_data)

        topics_data = [
            {"word_id": 10, "topic": "Tech", "raw_topic": "Tech"},
            {"word_id": 20, "topic": "Tech", "raw_topic": "Tech"},
            {"word_id": 30, "topic": "Tech", "raw_topic": "Tech"},
        ]
        db_mgr.insert_batch_fast("word_topics", topics_data)

        selected = [
            SelectedWord(id=10, lemma="word10", pos="noun", frequency_rank=10, cefr_level="A1", in_ngsl=True, source="kaikki"),
            SelectedWord(id=20, lemma="word20", pos="noun", frequency_rank=20, cefr_level="A1", in_ngsl=True, source="kaikki"),
            SelectedWord(id=30, lemma="word30", pos="noun", frequency_rank=30, cefr_level="A1", in_ngsl=True, source="kaikki"),
            SelectedWord(id=40, lemma="word40", pos="noun", frequency_rank=40, cefr_level="A1", in_ngsl=True, source="kaikki"),
        ]

        enriched, summary = enricher.validate_and_enrich(db_mgr, selected)
        assert len(enriched) == 4
        assert summary.total_words == 4
        assert summary.passed_all_gates == 0

        r10 = next(r for r in summary.gate_results if r.lemma == "word10")
        assert "def_en" in r10.missing_fields

        r20 = next(r for r in summary.gate_results if r.lemma == "word20")
        assert "ipa" in r20.missing_fields

        r30 = next(r for r in summary.gate_results if r.lemma == "word30")
        assert "sentence" in r30.missing_fields

        r40 = next(r for r in summary.gate_results if r.lemma == "word40")
        assert "topic" in r40.missing_fields
        # Word 40 has no topic in db, default "General & Everyday" in enriched list
        w40_entry = next(e for e in enriched if e["lemma"] == "word40")
        assert w40_entry["topic"] == "General & Everyday"

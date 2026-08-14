import json
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter
from src.export.json_exporter import JsonExporter
from src.pipeline.steps.export_core3000 import ExportCore3000Step
from src.pipeline.steps.export_json import ExportJsonStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "staging.duckdb")
    mgr.init_schema()

    mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "frequency_rank": 100, "cefr_level": "A1", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("definitions", [
        {"word_id": 1, "definition_en": "to move fast", "definition_vi": "chạy nhanh", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("sentences", [
        {"text_en": "He runs fast.", "text_vi": "Anh ấy chạy nhanh.", "source": "tatoeba"},
    ])
    mgr.insert_batch_fast("word_sentences", [{"word_id": 1, "sentence_id": 1}])
    mgr.insert_batch_fast("phrases", [
        {"phrase": "run away", "phrase_type": "phrasal_verb", "definition_en": "to escape", "definition_vi": "trốn thoát"},
    ])
    mgr.insert_batch_fast("word_topics", [{"word_id": 1, "topic": "Sports & Fitness", "raw_topic": "sports"}])

    yield mgr, tmp_path
    mgr.close()


def test_json_exporter_hierarchical_structure(db_mgr):
    staging_mgr, tmp_path = db_mgr
    json_path = tmp_path / "dataset.json"

    exporter = JsonExporter()
    count = exporter.export(staging_mgr, json_path)

    assert count == 1
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["version"] == "2.0"
    assert payload["metadata"]["total_words"] == 1
    assert payload["metadata"]["total_phrases"] == 1

    # Check nested word data
    word_entry = payload["vocabulary"][0]
    assert word_entry["lemma"] == "run"
    assert word_entry["pos"] == "verb"
    assert len(word_entry["definitions"]) == 1
    assert word_entry["definitions"][0]["definition_en"] == "to move fast"
    assert word_entry["definitions"][0]["definition_vi"] == "chạy nhanh"
    assert len(word_entry["example_sentences"]) == 1
    assert word_entry["example_sentences"][0]["text_en"] == "He runs fast."
    assert "Sports & Fitness" in word_entry["topics"]

    # Check phrases
    phrase_entry = payload["phrases"][0]
    assert phrase_entry["phrase"] == "run away"
    assert phrase_entry["definition_vi"] == "trốn thoát"


def test_export_step_classes():
    step_json = ExportJsonStep()
    assert step_json.name == "export_json"
    assert "dataset.json" in step_json.produces

    step_core = ExportCore3000Step()
    assert step_core.name == "export_core3000"
    assert "core_3000.db" in step_core.produces

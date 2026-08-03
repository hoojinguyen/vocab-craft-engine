"""
End-to-end tests for the Step 4H lexical relations & topics pipeline stage.
"""

import json
import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

import main as main_module
from src.db.staging_db import DatabaseManager


@pytest.fixture
def relation_environment(tmp_path: Path, monkeypatch):
    kaikki_file = tmp_path / "kaikki.jsonl"
    entries = [
        {"word": "dog", "pos": "noun",
         "senses": [{"glosses": ["An animal."], "topics": ["zoology"]}],
         "synonyms": [{"word": "hound"}, {"word": "give up the ghost"}],
         "hypernyms": [{"word": "animal"}]},
        {"word": "animal", "pos": "noun",
         "senses": [{"glosses": ["A living creature."], "topics": ["zoology"]}]},
        {"word": "quick", "pos": "adjective",
         "senses": [{"glosses": ["Fast."]}],
         "antonyms": [{"word": "slow"}]}
    ]
    kaikki_file.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    monkeypatch.setattr(main_module, "KAIKKI_JSON_PATH", kaikki_file)

    db_path = tmp_path / "pipeline.db"
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_schema()
    db_manager.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"},
        {"lemma": "animal", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 300, "cefr_level": "A1"},
        {"lemma": "quick", "pos": "adjective", "ipa_uk": None, "ipa_us": None, "frequency_rank": 900, "cefr_level": "A2"},
        {"lemma": "slow", "pos": "adjective", "ipa_uk": None, "ipa_us": None, "frequency_rank": 1100, "cefr_level": "A2"},
        {"lemma": "hound", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 8000, "cefr_level": "B2"}
    ])
    yield db_manager
    db_manager.close()


def test_run_relations_step_populates_db(relation_environment):
    db_manager = relation_environment
    args = argparse.Namespace(force_reset=False)

    stats = main_module.run_relations_step(db_manager, args)
    assert stats["relations"] > 0
    assert stats["topics"] > 0

    conn = db_manager.get_connection()
    cursor = conn.cursor()

    dog_id = db_manager.get_word_id_by_lemma("dog")
    animal_id = db_manager.get_word_id_by_lemma("animal")
    hound_id = db_manager.get_word_id_by_lemma("hound")
    quick_id = db_manager.get_word_id_by_lemma("quick")
    slow_id = db_manager.get_word_id_by_lemma("slow")

    # Primary relations from the dog entry
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ? ORDER BY relation_type, target_text;", (dog_id,))
    rows = cursor.fetchall()
    assert ("hypernym", "animal", animal_id, 0) in rows
    assert ("synonym", "give up the ghost", None, 0) in rows  # multi-word, unlinked
    assert ("synonym", "hound", hound_id, 0) in rows

    # Inverse row: natural hypernym (dog -> animal) generates hyponym (animal -> dog), inverted=1
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ? AND relation_type = 'hyponym';", (animal_id,))
    inv = cursor.fetchall()
    assert ("hyponym", "dog", dog_id, 1) in inv

    # Antonyms linked (quick -> slow)
    cursor.execute("SELECT relation_type, target_text, target_word_id, inverted FROM word_relations WHERE word_id = ?;", (quick_id,))
    assert ("antonym", "slow", slow_id, 0) in cursor.fetchall()

    # Topics mapped
    cursor.execute("SELECT topic, raw_topic FROM word_topics WHERE word_id = ?;", (dog_id,))
    assert ("Nature & Animals", "zoology") in cursor.fetchall()


def test_run_relations_step_checkpoint_skips(relation_environment, monkeypatch):
    db_manager = relation_environment
    args = argparse.Namespace(force_reset=False)

    monkeypatch.setattr(main_module, "RELATION_CHECKPOINT", 10)
    monkeypatch.setattr(main_module, "TOPIC_CHECKPOINT", 10)

    dog_id = db_manager.get_word_id_by_lemma("dog")
    db_manager.insert_word_relations_batch([
        {"word_id": dog_id, "relation_type": "synonym", "target_text": f"seed{i}",
         "target_word_id": None, "inverted": 0, "source": "synonyms"}
        for i in range(12)
    ])
    db_manager.insert_word_topics_batch([
        {"word_id": dog_id, "topic": f"Seed{i}", "raw_topic": "seed"} for i in range(12)
    ])

    with patch.object(main_module, "RelationParser") as mock_parser:
        stats = main_module.run_relations_step(db_manager, args)
        mock_parser.assert_not_called()

    assert stats["relations"] == 12
    assert stats["links"] == 0
    assert stats["topics"] == 12

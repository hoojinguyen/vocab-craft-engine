"""
Unit tests for DatabaseManager in src.db.staging_db
"""

import pytest
import sqlite3
from pathlib import Path
from src.db.staging_db import DatabaseManager


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_english_dataset.db"
    db_manager = DatabaseManager(db_path=db_file)
    db_manager.init_schema()
    yield db_manager
    db_manager.close()


def test_init_schema_creates_tables_and_indexes(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()

    # Check tables existence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "words", "definitions", "collocations", "sentence_patterns",
        "sentences", "dialogue_trees", "dialogue_nodes",
        "reflex_drills", "word_sentence_map"
    }
    assert expected_tables.issubset(tables)


def test_insert_words_batch_and_idempotency(temp_db: DatabaseManager):
    words = [
        {"lemma": "run", "pos": "verb", "ipa_uk": "rʌn", "ipa_us": "rʌn", "frequency_rank": 150, "cefr_level": "A1"},
        {"lemma": "apple", "pos": "noun", "ipa_uk": "ˈæp.əl", "ipa_us": "ˈæp.əl", "frequency_rank": 1200, "cefr_level": "A1"}
    ]

    temp_db.insert_words_batch(words)
    run_id = temp_db.get_word_id_by_lemma("run")
    apple_id = temp_db.get_word_id_by_lemma("apple")

    assert run_id is not None
    assert apple_id is not None

    # Test idempotency (INSERT OR IGNORE duplicate lemma)
    temp_db.insert_words_batch(words)
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM words;")
    count = cursor.fetchone()[0]
    assert count == 2


def test_insert_definitions_batch(temp_db: DatabaseManager):
    words = [{"lemma": "test", "pos": "noun", "ipa_uk": "test", "ipa_us": "test", "frequency_rank": 500, "cefr_level": "A1"}]
    temp_db.insert_words_batch(words)
    word_id = temp_db.get_word_id_by_lemma("test")

    definitions = [
        {"word_id": word_id, "definition_en": "A procedure intended to establish the quality.", "definition_vi": "Bài kiểm tra", "example": "This is a test.", "source": "Kaikki"}
    ]
    temp_db.insert_definitions_batch(definitions)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT definition_vi FROM definitions WHERE word_id = ?;", (word_id,))
    res = cursor.fetchone()
    assert res[0] == "Bài kiểm tra"


def test_foreign_key_check(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_key_check;")
    violations = cursor.fetchall()
    assert len(violations) == 0


def test_phrase_tables_exist(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"phrases", "phrase_sentences"}.issubset(tables)


def test_insert_phrases_batch_and_idempotency(temp_db: DatabaseManager):
    phrases = [
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": "Chúc may mắn!", "ipa": "breɪk ə leɡ",
         "audio_std": None, "audio_fast": None, "audio_status": "ok"},
        {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "phrasal verb",
         "cefr_level": "A2", "difficulty_score": 1.8, "definition_en": "To stop trying.",
         "definition_vi": "Từ bỏ", "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ]
    temp_db.insert_phrases_batch(phrases)

    assert temp_db.get_phrase_id_by_text("break a leg") is not None
    assert temp_db.get_phrase_id_by_text("give up") is not None

    # Idempotency: INSERT OR IGNORE on duplicate phrase
    temp_db.insert_phrases_batch(phrases)
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM phrases;")
    assert cursor.fetchone()[0] == 2


def test_insert_phrase_sentences_batch_and_update_audio(temp_db: DatabaseManager):
    temp_db.insert_phrases_batch([
        {"phrase": "break a leg", "phrase_type": "idiom", "pos": "idiom",
         "cefr_level": "B1", "difficulty_score": 2.5, "definition_en": "Good luck!",
         "definition_vi": None, "ipa": None,
         "audio_std": None, "audio_fast": None, "audio_status": "ok"}
    ])
    temp_db.insert_sentences_batch([
        {"text_en": "Break a leg at the show tonight!", "text_vi": None,
         "difficulty_score": 2.0, "cefr_level": "B1", "audio_path": None, "source": "Tatoeba"}
    ])
    phrase_id = temp_db.get_phrase_id_by_text("break a leg")

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sentences WHERE text_en = ?;", ("Break a leg at the show tonight!",))
    sentence_id = cursor.fetchone()[0]

    temp_db.insert_phrase_sentences_batch([
        {"phrase_id": phrase_id, "sentence_id": sentence_id, "rank": 1}
    ])
    temp_db.update_phrase_audio(phrase_id, "audio/break_1_std.mp3", "audio/break_1_fast.mp3", "ok")

    cursor.execute("SELECT audio_std, audio_fast, audio_status FROM phrases WHERE id = ?;", (phrase_id,))
    row = cursor.fetchone()
    assert row == ("audio/break_1_std.mp3", "audio/break_1_fast.mp3", "ok")


def test_relation_tables_exist(temp_db: DatabaseManager):
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"word_relations", "word_topics"}.issubset(tables)


def test_insert_word_relations_batch_and_idempotency(temp_db: DatabaseManager):
    temp_db.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"},
        {"lemma": "animal", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 300, "cefr_level": "A1"},
        {"lemma": "hound", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 8000, "cefr_level": "B2"}
    ])
    dog_id = temp_db.get_word_id_by_lemma("dog")
    animal_id = temp_db.get_word_id_by_lemma("animal")
    hound_id = temp_db.get_word_id_by_lemma("hound")

    relations = [
        {"word_id": dog_id, "relation_type": "synonym", "target_text": "hound",
         "target_word_id": hound_id, "inverted": 0, "source": "synonyms"},
        {"word_id": dog_id, "relation_type": "hypernym", "target_text": "animal",
         "target_word_id": animal_id, "inverted": 0, "source": "hypernyms"},
    ]
    temp_db.insert_word_relations_batch(relations)
    # Idempotency: UNIQUE (word_id, relation_type, target_text) + OR IGNORE
    temp_db.insert_word_relations_batch(relations)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM word_relations;")
    assert cursor.fetchone()[0] == 2


def test_insert_word_topics_batch_and_idempotency(temp_db: DatabaseManager):
    temp_db.insert_words_batch([
        {"lemma": "dog", "pos": "noun", "ipa_uk": None, "ipa_us": None, "frequency_rank": 100, "cefr_level": "A1"}
    ])
    dog_id = temp_db.get_word_id_by_lemma("dog")

    topics = [{"word_id": dog_id, "topic": "Nature & Animals", "raw_topic": "zoology"}]
    temp_db.insert_word_topics_batch(topics)
    temp_db.insert_word_topics_batch(topics)

    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM word_topics;")
    assert cursor.fetchone()[0] == 1


def test_get_max_sentence_id_and_count_by_source(temp_db):
    temp_db.insert_sentences_batch([
        {"text_en": "Hello world.", "text_vi": "Xin chào.", "difficulty_score": 1.0,
         "cefr_level": "A1", "audio_path": None, "source": "Tatoeba"},
        {"text_en": "Good morning.", "text_vi": "Chào buổi sáng.", "difficulty_score": 1.0,
         "cefr_level": "A1", "audio_path": None, "source": "OpenSubtitles"},
    ])
    assert temp_db.get_max_sentence_id() >= 2
    assert temp_db.count_sentences_by_source("OpenSubtitles") == 1
    assert temp_db.count_sentences_by_source("Missing") == 0

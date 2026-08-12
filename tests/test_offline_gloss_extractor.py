import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock
from src.nlp.offline_gloss_extractor import OfflineGlossExtractor

def test_offline_gloss_extractor_lookup(tmp_path):
    kaikki_sample = tmp_path / "kaikki_sample.json"
    kaikki_sample.write_text(
        '{"word": "apple", "lang_code": "vi", "senses": [{"glosses": ["quả táo"]}]}\n'
        '{"word": "give up", "lang_code": "vi", "senses": [{"glosses": ["từ bỏ"]}]}\n'
        '{"word": "banana", "lang_code": "en", "senses": [{"glosses": ["banana"]}]}\n'
        '{"word": "cat", "lang_code": "vi", "senses": [{"glosses": ["the and of"]}]}\n',  # invalid English passthrough
        encoding="utf-8"
    )
    extractor = OfflineGlossExtractor(kaikki_path=kaikki_sample)
    assert extractor.get_translation("apple") == "quả táo"
    assert extractor.get_translation("  APPLE  ") == "quả táo"
    assert extractor.get_translation("give up") == "từ bỏ"
    assert extractor.get_translation("banana") is None
    assert extractor.get_translation("nonexistent_xyz") is None

def test_offline_gloss_extractor_nonexistent_file(tmp_path):
    non_existent = tmp_path / "does_not_exist.json"
    extractor = OfflineGlossExtractor(kaikki_path=non_existent)
    assert extractor.get_translation("apple") is None

def test_offline_gloss_extractor_backfill(tmp_path):
    kaikki_sample = tmp_path / "kaikki_sample.json"
    kaikki_sample.write_text(
        '{"word": "apple", "lang_code": "vi", "senses": [{"glosses": ["quả táo"]}]}\n'
        '{"word": "give up", "lang_code": "vi", "senses": [{"glosses": ["từ bỏ"]}]}\n'
        '{"word": "break down", "lang_code": "vi", "senses": [{"glosses": ["hỏng hóc"]}]}\n',
        encoding="utf-8"
    )
    extractor = OfflineGlossExtractor(kaikki_path=kaikki_sample)

    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE words (id INTEGER PRIMARY KEY, lemma TEXT);")
    cursor.execute("CREATE TABLE definitions (id INTEGER PRIMARY KEY, word_id INTEGER, definition_vi TEXT);")
    cursor.execute("CREATE TABLE collocations (id INTEGER PRIMARY KEY, phrase TEXT, meaning_vi TEXT);")
    cursor.execute("CREATE TABLE phrases (id INTEGER PRIMARY KEY, phrase TEXT, definition_vi TEXT);")

    cursor.execute("INSERT INTO words VALUES (1, 'apple'), (2, 'banana');")
    cursor.execute("INSERT INTO definitions VALUES (10, 1, NULL), (11, 2, '');")
    cursor.execute("INSERT INTO collocations VALUES (20, 'give up', NULL), (21, 'take off', 'cởi ra');")
    cursor.execute("INSERT INTO phrases VALUES (30, 'break down', ''), (31, 'keep on', 'tiếp tục');")
    conn.commit()

    db_manager = MagicMock()
    db_manager.get_connection.return_value = conn

    res = extractor.backfill_db_glosses(db_manager)

    assert res == {
        "definitions": 1,
        "collocations": 1,
        "phrases": 1
    }

    # Verify updated values in DB
    cursor.execute("SELECT definition_vi FROM definitions WHERE id = 10;")
    assert cursor.fetchone()[0] == "quả táo"
    cursor.execute("SELECT definition_vi FROM definitions WHERE id = 11;")
    assert cursor.fetchone()[0] == ""  # unchanged

    cursor.execute("SELECT meaning_vi FROM collocations WHERE id = 20;")
    assert cursor.fetchone()[0] == "từ bỏ"

    cursor.execute("SELECT definition_vi FROM phrases WHERE id = 30;")
    assert cursor.fetchone()[0] == "hỏng hóc"

    conn.close()

import sqlite3
import pytest
from pathlib import Path
from src.export.schema import SQLITE_INDEXES, SQLITE_SCHEMA
from src.export.verifier import DatasetVerifier, VerificationReport


def test_dataset_verifier_valid_database(tmp_path: Path):
    db_file = tmp_path / "valid.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SQLITE_SCHEMA)
    conn.executescript(SQLITE_INDEXES)

    # Insert valid test data
    conn.execute("INSERT INTO words (id, lemma, pos) VALUES (1, 'run', 'verb')")
    conn.execute("INSERT INTO sentences (id, text_en, text_vi) VALUES (1, 'He runs.', 'Anh ấy chạy.')")
    conn.execute("INSERT INTO word_sentences (word_id, sentence_id) VALUES (1, 1)")
    conn.execute("INSERT INTO reflex_drills (id, sentence_id, drill_type, correct_answer, distractors_json) VALUES (1, 1, 'cloze', 'runs', '[\"walks\", \"jumps\", \"flies\"]')")
    conn.execute("INSERT INTO dataset_metadata (key, value) VALUES ('version', '2.0')")
    conn.commit()
    conn.close()

    verifier = DatasetVerifier()
    report: VerificationReport = verifier.verify(db_file)

    assert report.is_valid is True
    assert report.foreign_key_violations == 0
    assert report.integrity_check_passed is True
    assert report.invalid_json_count == 0
    assert report.table_counts["words"] == 1
    assert report.table_counts["sentences"] == 1


def test_dataset_verifier_catches_foreign_key_violation(tmp_path: Path):
    db_file = tmp_path / "invalid_fk.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.executescript(SQLITE_SCHEMA)

    # Insert sentence link pointing to non-existent word_id = 999
    conn.execute("INSERT INTO sentences (id, text_en, text_vi) VALUES (1, 'Test.', 'Thử.')")
    conn.execute("INSERT INTO word_sentences (word_id, sentence_id) VALUES (999, 1)")
    conn.commit()
    conn.close()

    verifier = DatasetVerifier()
    report = verifier.verify(db_file)

    assert report.is_valid is False
    assert report.foreign_key_violations > 0

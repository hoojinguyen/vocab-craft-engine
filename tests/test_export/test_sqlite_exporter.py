import sqlite3
import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.export.sqlite_exporter import SqliteExporter


@pytest.fixture
def test_staging(tmp_path: Path):
    db_file = tmp_path / "staging_for_export.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "frequency_rank": 50, "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "fast", "pos": "adj", "frequency_rank": 150, "cefr_level": "A1", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("definitions", [
        {"word_id": 1, "definition_en": "to move swiftly", "definition_vi": "chạy nhanh", "source": "kaikki"},
    ])
    mgr.insert_batch_fast("sentences", [
        {"text_en": "He runs fast.", "text_vi": "Anh ấy chạy nhanh.", "cefr_level": "A1", "source": "tatoeba"},
    ])
    mgr.insert_batch_fast("word_sentences", [{"word_id": 1, "sentence_id": 1}])
    mgr.insert_batch_fast("phrases", [{"phrase": "run away", "phrase_type": "phrasal_verb", "definition_en": "to escape"}])
    mgr.insert_batch_fast("phrase_sentences", [{"phrase_id": 1, "sentence_id": 1, "rank": 1}])
    mgr.insert_batch_fast("word_topics", [{"word_id": 1, "topic": "Sports", "raw_topic": "sports"}])
    mgr.insert_batch_fast("reflex_drills", [{
        "sentence_id": 1,
        "drill_type": "cloze",
        "prompt_text": "He ___ fast.",
        "correct_answer": "runs",
        "distractors_json": '["walks", "jumps", "flies"]',
        "target_time_ms": 2500,
    }])
    mgr.insert_batch_fast("dialogue_trees", [{"title": "Cafe", "topic": "Food", "cefr_level": "A1"}])
    mgr.insert_batch_fast("dialogue_nodes", [{"tree_id": 1, "speaker_role": "A", "choice_label": "Hello"}])

    yield mgr
    mgr.close()


def test_sqlite_exporter_full_export_and_metadata(test_staging: DuckDBManager, tmp_path: Path):
    target_sqlite = tmp_path / "english_dataset.db"
    exporter = SqliteExporter()
    exported_counts = exporter.export(test_staging, target_sqlite)

    assert exported_counts["words"] == 2
    assert exported_counts["definitions"] == 1
    assert exported_counts["sentences"] == 1
    assert exported_counts["word_sentences"] == 1
    assert exported_counts["phrases"] == 1
    assert exported_counts["phrase_sentences"] == 1
    assert exported_counts["word_topics"] == 1
    assert exported_counts["reflex_drills"] == 1
    assert exported_counts["dialogue_trees"] == 1
    assert exported_counts["dialogue_nodes"] == 1

    # Verify SQLite DB
    conn = sqlite3.connect(str(target_sqlite))
    cur = conn.cursor()

    # Check metadata
    meta = dict(cur.execute("SELECT key, value FROM dataset_metadata").fetchall())
    assert meta["version"] == "2.0"
    assert int(meta["total_words"]) == 2
    assert int(meta["total_sentences"]) == 1
    assert int(meta["total_phrases"]) == 1

    # Check indexes exist
    indexes = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    assert "idx_words_lemma" in indexes
    assert "idx_reflex_drills_sent" in indexes

    conn.close()

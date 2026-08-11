import sqlite3
import pytest
from pathlib import Path
from src.export.sqlite_exporter import (
    SQLiteExporter,
    POS_MAP,
    POS_REV_MAP,
    CEFR_MAP,
    CEFR_REV_MAP,
    DRILL_MAP,
    RELATION_MAP,
    QUESTION_TYPE_MAP,
    TARGET_TYPE_MAP,
)

@pytest.fixture
def dummy_db(tmp_path) -> Path:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("""
        CREATE TABLE words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lemma TEXT NOT NULL UNIQUE,
            pos TEXT,
            ipa_uk TEXT,
            ipa_us TEXT,
            frequency_rank INTEGER,
            cefr_level TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE reflex_drills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sentence_id INTEGER,
            drill_type TEXT,
            prompt_text TEXT,
            correct_answer TEXT,
            distractors_json TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text_en TEXT,
            cefr_level TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE word_relations (
            word_id INTEGER,
            relation_type TEXT,
            target_word_id INTEGER,
            target_text TEXT,
            PRIMARY KEY (word_id, relation_type, target_text)
        );
    """)
    cursor.execute("""
        CREATE TABLE word_topics (
            word_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            PRIMARY KEY (word_id, topic)
        );
    """)
    cursor.execute("""
        CREATE TABLE phrase_sentences (
            phrase_id INTEGER NOT NULL,
            sentence_id INTEGER NOT NULL,
            PRIMARY KEY (phrase_id, sentence_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE sentence_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_name TEXT,
            structure_json TEXT,
            example_en TEXT,
            example_vi TEXT,
            cefr_level TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE pattern_sentences (
            pattern_id INTEGER NOT NULL,
            sentence_id INTEGER NOT NULL,
            matched_tokens_json TEXT,
            PRIMARY KEY (pattern_id, sentence_id)
        );
    """)
    cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('apple', 'noun', 'A1');")
    cursor.execute("INSERT INTO sentences (text_en, cefr_level) VALUES ('An apple a day.', 'A1');")
    cursor.execute("INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer) VALUES (1, 'speed_translation', 'quả táo', 'apple');")
    cursor.execute("INSERT INTO word_relations (word_id, relation_type, target_text) VALUES (1, 'synonym', 'fruit');")
    cursor.execute("INSERT INTO word_topics (word_id, topic) VALUES (1, 'food');")
    cursor.execute("INSERT INTO phrase_sentences (phrase_id, sentence_id) VALUES (1, 1);")
    cursor.execute("INSERT INTO sentence_patterns (pattern_name) VALUES ('it_is_adj_to_v');")
    cursor.execute("INSERT INTO pattern_sentences (pattern_id, sentence_id) VALUES (1, 1);")
    conn.commit()
    conn.close()
    return db_path

def test_constants():
    assert POS_MAP["noun"] == 1
    assert POS_REV_MAP[1] == "noun"
    assert CEFR_MAP["A1"] == 1
    assert CEFR_REV_MAP[1] == "A1"
    assert DRILL_MAP["speed_translation"] == 1
    assert RELATION_MAP["synonym"] == 1
    assert QUESTION_TYPE_MAP["word_mcq"] == 1
    assert TARGET_TYPE_MAP["word"] == 1


def test_optimize_and_package_enum_migration(dummy_db):
    exporter = SQLiteExporter(db_path=dummy_db)
    res = exporter.optimize_and_package()
    assert res["size_bytes"] > 0

    conn = sqlite3.connect(str(dummy_db))
    cursor = conn.cursor()
    # Check words table has TINYINT integer enum values
    row = cursor.execute("SELECT pos, cefr_level FROM words WHERE lemma = 'apple'").fetchone()
    assert isinstance(row[0], int)  # 1 for noun
    assert row[0] == 1
    assert isinstance(row[1], int)  # 1 for A1
    assert row[1] == 1

    # Check words table schema contains UNIQUE constraint
    words_sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='words'").fetchone()[0]
    assert "UNIQUE" in words_sql

    # Check duplicate insert into words raises IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("INSERT INTO words (lemma, pos, cefr_level) VALUES ('apple', 1, 1);")

    # Check WITHOUT ROWID link tables
    for tbl in ["word_topics", "word_relations", "phrase_sentences", "pattern_sentences"]:
        tbl_sql = cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tbl}'").fetchone()[0]
        assert "WITHOUT ROWID" in tbl_sql.upper()

    # Check reflex_drills table drill_type
    drill_row = cursor.execute("SELECT drill_type FROM reflex_drills WHERE id = 1").fetchone()
    assert isinstance(drill_row[0], int)
    assert drill_row[0] == 1  # 1 for speed_translation

    # Check word_relations table relation_type
    rel_row = cursor.execute("SELECT relation_type FROM word_relations WHERE word_id = 1").fetchone()
    assert isinstance(rel_row[0], int)
    assert rel_row[0] == 1  # 1 for synonym

    # Check sentences table cefr_level
    sent_row = cursor.execute("SELECT cefr_level FROM sentences WHERE id = 1").fetchone()
    assert isinstance(sent_row[0], int)
    assert sent_row[0] == 1  # 1 for A1

    # Check v_words view maps back to text
    view_row = cursor.execute("SELECT pos, cefr_level FROM v_words WHERE lemma = 'apple'").fetchone()
    assert view_row[0] == 'noun'
    assert view_row[1] == 'A1'
    conn.close()

def test_fts5_external_content_and_covering_indexes(dummy_db):
    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    cursor = conn.cursor()

    # Verify words_fts virtual table exists
    fts_row = cursor.execute("SELECT rowid, lemma FROM words_fts WHERE words_fts MATCH 'appl*'").fetchone()
    assert fts_row is not None
    assert fts_row[1] == 'apple'

    # Verify covering index exists
    idx_list = [row[1] for row in cursor.execute("PRAGMA index_list('words');").fetchall()]
    assert 'idx_words_lemma_cov' in idx_list
    conn.close()


def test_benchmark_all_queries_sla(dummy_db):
    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "lemma_lookup_ms" in benchmarks
    assert "fts_search_ms" in benchmarks
    assert "reflex_sampling_ms" in benchmarks
    assert "topic_relation_join_ms" in benchmarks
    assert "pattern_lookup_ms" in benchmarks

    # Assert all query benchmarks are under 5.0 ms SLA
    for key, val in benchmarks.items():
        assert val < 5.0, f"Query benchmark {key} exceeded SLA: {val} ms"


def test_words_dynamic_columns_preservation(tmp_path):
    db_path = tmp_path / "extra_cols.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lemma TEXT NOT NULL UNIQUE,
            pos TEXT,
            cefr_level TEXT,
            audio_std TEXT,
            audio_fast TEXT,
            audio_status TEXT,
            custom_extra TEXT
        );
    """)
    conn.execute(
        "INSERT INTO words (lemma, pos, cefr_level, audio_std, audio_fast, audio_status, custom_extra) "
        "VALUES ('banana', 'noun', 'A2', 'std.mp3', 'fast.mp3', 'ok', 'extra_val');"
    )
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=db_path)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(words);")
    col_names = [col[1] for col in cursor.fetchall()]

    for expected_col in ["id", "lemma", "pos", "cefr_level", "audio_std", "audio_fast", "audio_status", "custom_extra"]:
        assert expected_col in col_names, f"Column {expected_col} was lost during migration!"

    row = cursor.execute(
        "SELECT lemma, pos, cefr_level, audio_std, audio_fast, audio_status, custom_extra FROM words WHERE lemma = 'banana'"
    ).fetchone()
    assert row == ('banana', 1, 2, 'std.mp3', 'fast.mp3', 'ok', 'extra_val')
    conn.close()


def test_pattern_sentences_exporter_without_rowid_and_sla(dummy_db):
    # Setup pattern_sentences in dummy_db
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS sentence_patterns (id INTEGER PRIMARY KEY, pattern_name TEXT, structure_json TEXT, example_en TEXT, example_vi TEXT, cefr_level TEXT);")
    conn.execute("CREATE TABLE IF NOT EXISTS pattern_sentences (pattern_id INTEGER, sentence_id INTEGER, matched_tokens_json TEXT, PRIMARY KEY(pattern_id, sentence_id));")
    conn.execute("INSERT OR IGNORE INTO sentence_patterns (id, pattern_name) VALUES (1, 'it_is_adj_to_v');")
    conn.execute("INSERT OR IGNORE INTO pattern_sentences (pattern_id, sentence_id) VALUES (1, 1);")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Verify WITHOUT ROWID
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pattern_sentences';").fetchone()[0]
    assert "WITHOUT ROWID" in sql.upper()
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "pattern_lookup_ms" in benchmarks
    assert benchmarks["pattern_lookup_ms"] < 1.0


def test_v_dialogue_nodes_view_and_sla(dummy_db):
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS dialogue_trees (id INTEGER PRIMARY KEY, title TEXT, topic TEXT, cefr_level TEXT, root_node_id INTEGER);")
    conn.execute("CREATE TABLE IF NOT EXISTS dialogue_nodes (id INTEGER PRIMARY KEY, tree_id INTEGER, parent_node_id INTEGER, choice_label TEXT, speaker_role TEXT, sentence_id INTEGER);")
    conn.execute("INSERT INTO dialogue_trees VALUES (1, 'Ordering Coffee', 'Dining', 'A2', 1);")
    conn.execute("INSERT INTO dialogue_nodes VALUES (1, 1, NULL, NULL, 'A', 1);")
    conn.execute("INSERT INTO dialogue_nodes VALUES (2, 1, 1, 'Hot Latte', 'B', 1);")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Check v_dialogue_nodes view exists
    row = conn.execute("SELECT node_id, choice_label, text_en FROM v_dialogue_nodes WHERE tree_id = 1 AND parent_node_id = 1;").fetchone()
    assert row is not None
    assert row[1] == 'Hot Latte'
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "scenario_traversal_ms" in benchmarks
    assert benchmarks["scenario_traversal_ms"] < 0.5


def test_v_quiz_questions_view_and_sla(dummy_db):
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS quiz_questions (id INTEGER PRIMARY KEY, question_type TEXT, target_type TEXT, target_id INTEGER, prompt_text TEXT, correct_answer TEXT, options_json TEXT, cefr_level TEXT);")
    conn.execute("INSERT INTO quiz_questions VALUES (1, 'word_mcq', 'word', 1, 'abandon', 'rời bỏ', '[\"rời bỏ\", \"đạt được\"]', 'B2');")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Verify Integer Enum Migration (word_mcq -> 1, word -> 1, B2 -> integer code)
    row = conn.execute("SELECT question_type, target_type FROM quiz_questions WHERE id = 1;").fetchone()
    assert isinstance(row[0], int)
    assert row[0] == 1
    assert isinstance(row[1], int)
    assert row[1] == 1

    # Verify v_quiz_questions View
    v_row = conn.execute("SELECT quiz_id, prompt_text FROM v_quiz_questions WHERE quiz_id = 1;").fetchone()
    assert v_row is not None
    assert v_row[1] == 'abandon'
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "quiz_fetch_ms" in benchmarks
    assert benchmarks["quiz_fetch_ms"] < 1.0








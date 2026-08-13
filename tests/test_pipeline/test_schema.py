import duckdb
from src.db.schema import STAGING_SCHEMA, INTERNAL_SCHEMA, STAGING_TABLES, INTERNAL_TABLES


def test_staging_schema_creates_all_tables():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    for table_name in STAGING_TABLES:
        assert table_name in tables, f"Missing staging table: {table_name}"
    conn.close()


def test_internal_schema_creates_meta_tables():
    conn = duckdb.connect(":memory:")
    conn.execute(INTERNAL_SCHEMA)
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    for table_name in INTERNAL_TABLES:
        assert table_name in tables, f"Missing internal table: {table_name}"
    conn.close()


def test_staging_tables_list_has_11_tables():
    """Spec says 10 (dialogue as one unit) but code has 11 separate tables."""
    assert len(STAGING_TABLES) == 11


def test_internal_tables_list_has_4_tables():
    assert len(INTERNAL_TABLES) == 4


def test_words_unique_constraint():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    conn.execute("INSERT INTO words (id, lemma, pos, source) VALUES (1, 'run', 'verb', 'kaikki')")
    conn.execute("INSERT INTO words (id, lemma, pos, source) VALUES (2, 'run', 'noun', 'kaikki')")  # different POS OK
    try:
        conn.execute("INSERT INTO words (id, lemma, pos, source) VALUES (3, 'run', 'verb', 'wordnet')")  # duplicate lemma+pos
        assert False, "Should have raised duplicate constraint error"
    except duckdb.ConstraintException:
        pass
    conn.close()


def test_phrases_has_phrase_type_column():
    conn = duckdb.connect(":memory:")
    conn.execute(STAGING_SCHEMA)
    conn.execute("""
        INSERT INTO phrases (id, phrase, phrase_type, definition_en)
        VALUES (1, 'break down', 'phrasal_verb', 'to stop working')
    """)
    row = conn.execute("SELECT phrase_type FROM phrases WHERE phrase = 'break down'").fetchone()
    assert row[0] == "phrasal_verb"
    conn.close()

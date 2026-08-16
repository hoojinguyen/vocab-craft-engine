import duckdb

from src.learning.schema import GRAPH_TABLES, MIGRATIONS


def test_initial_graph_migration_creates_every_graph_table():
    conn = duckdb.connect(":memory:")
    for _, sql in MIGRATIONS:
        conn.execute(sql)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert set(GRAPH_TABLES).issubset(tables)
    assert "graph_schema_migrations" in tables

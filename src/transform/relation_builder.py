"""Lexical Relation Deduplicator."""

from src.db.duckdb_manager import DuckDBManager


class RelationBuilder:
    def deduplicate(self, db_mgr: DuckDBManager) -> int:
        return db_mgr.count_rows("word_relations")

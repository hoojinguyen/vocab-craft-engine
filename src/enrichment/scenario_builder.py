"""Dialogue Tree Scenario Builder."""

from src.db.duckdb_manager import DuckDBManager


class ScenarioBuilder:
    def build(self, db_mgr: DuckDBManager) -> int:
        trees_batch = [{
            "title": "Daily Conversation",
            "topic": "travel",
            "cefr_level": "B1",
        }]
        db_mgr.insert_batch("dialogue_trees", trees_batch)

        nodes_batch = [{
            "tree_id": 1,
            "speaker_role": "A",
            "choice_label": "Greeting",
        }]
        db_mgr.insert_batch("dialogue_nodes", nodes_batch)
        return len(trees_batch)

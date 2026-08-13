import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.scenario_builder import ScenarioBuilder

logger = logging.getLogger(__name__)


class ScenarioTreesStep(BaseStep):
    name = "scenario_trees"
    description = "Build branching interactive dialogue trees"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM dialogue_trees;")
            trees_count = cursor.fetchone()[0]
            if trees_count > 0:
                return True, f"{trees_count} dialogue trees already exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("Building Interactive Dialogue Trees...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        scenario_builder = ScenarioBuilder()

        try:
            scenarios = scenario_builder.build_sample_scenarios()
            cursor.execute("DELETE FROM dialogue_nodes;")
            cursor.execute("DELETE FROM dialogue_trees;")

            nodes_count = 0
            for sc in scenarios:
                cursor.execute("""
                    INSERT INTO dialogue_trees (title, topic, cefr_level)
                    VALUES (?, ?, ?);
                """, (sc["title"], sc["topic"], sc["cefr_level"]))
                tree_id = cursor.lastrowid

                local_node_map = {}
                first_node_id = None
                for node in sc["nodes"]:
                    cursor.execute("""
                        INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, source)
                        VALUES (?, ?, ?, ?, ?);
                    """, (node["text_en"], node["text_vi"], 2.0, sc["cefr_level"], "DialogueTree"))

                    cursor.execute("SELECT id FROM sentences WHERE text_en = ?;", (node["text_en"],))
                    s_row = cursor.fetchone()
                    if not s_row:
                        raise RuntimeError(f"Failed to find or insert sentence for dialogue node: {node['text_en']}")
                    sent_id = s_row[0]
                    cursor.execute("UPDATE sentences SET audio_path = ? WHERE id = ?;", (f"sent_{sent_id}_std.mp3", sent_id))

                    parent_db_id = local_node_map.get(node.get("parent_index"))

                    cursor.execute("""
                        INSERT INTO dialogue_nodes (tree_id, parent_node_id, sentence_id, speaker_role, choice_label)
                        VALUES (?, ?, ?, ?, ?);
                    """, (tree_id, parent_db_id, sent_id, node["speaker_role"], node["choice_label"]))
                    node_db_id = cursor.lastrowid
                    if first_node_id is None:
                        first_node_id = node_db_id
                    local_node_map[node["node_index"]] = node_db_id
                    nodes_count += 1

                if first_node_id is not None:
                    cursor.execute("UPDATE dialogue_trees SET root_node_id = ? WHERE id = ?;", (first_node_id, tree_id))

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Failed to build scenario trees: %s", e)
            raise e

        logger.info("Completed: %s dialogue trees, %s nodes.", len(scenarios), nodes_count)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=len(scenarios))

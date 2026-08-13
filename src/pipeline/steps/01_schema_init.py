import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import SENTENCE_LINK_CHECKPOINT, KAIKKI_INGEST_CHECKPOINT

logger = logging.getLogger(__name__)

class SchemaInitStep(BaseStep):
    name = "schema_init"
    description = "Initialize SQLite database schema and handle force-reset"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 1] Initializing SQLite Database Schema...")
        if getattr(context.args, "force_reset", False) and context.db_manager.db_path.exists():
            logger.info("   -> Force-reset flag active. Wiping existing database tables...")
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            conn.execute("PRAGMA foreign_keys = OFF;")
            tables_to_drop = [
                "phrase_sentences", "phrases", "word_relations", "word_topics", "word_sentence_map",
                "reflex_drills", "dialogue_nodes", "dialogue_trees", "sentences", "sentence_patterns",
                "collocations", "definitions", "words"
            ]
            for tbl in tables_to_drop:
                cursor.execute(f"DROP TABLE IF EXISTS {tbl};")
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON;")
            SENTENCE_LINK_CHECKPOINT.unlink(missing_ok=True)
            KAIKKI_INGEST_CHECKPOINT.unlink(missing_ok=True)
            logger.info("   -> Cleared stale checkpoints for fresh re-link and ingestion.")


        context.db_manager.init_schema()
        logger.info("[Step 1] Schema initialized successfully.")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=1)

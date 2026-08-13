import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.reflex_builder import ReflexBuilder

logger = logging.getLogger(__name__)


class ReflexDrillsStep(BaseStep):
    name = "reflex_drills"
    description = "Generate Speed Reflex Drill Cards (< 2.5s target)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sentences WHERE text_vi IS NOT NULL AND TRIM(text_vi) != '';")
            total_sentences = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT sentence_id) FROM reflex_drills WHERE drill_type = 'speed_translation';")
            existing_drills = cursor.fetchone()[0]

            if existing_drills >= total_sentences and total_sentences > 0:
                return True, f"{existing_drills:,} reflex drill cards already exist (complete)."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 6] Generating Speed Reflex Drill Cards...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, text_en, text_vi, cefr_level FROM sentences WHERE text_vi IS NOT NULL AND TRIM(text_vi) != '';")
        stored_sentences = cursor.fetchall()
        sentence_pool = [
            {"id": r[0], "text_en": r[1], "text_vi": r[2], "cefr_level": r[3]}
            for r in stored_sentences
            if r[2] and r[2].strip()
        ]

        try:
            cursor.execute("SELECT count(*) FROM reflex_drills WHERE drill_type = 'speed_translation';")
            existing_drills = cursor.fetchone()[0]
            if existing_drills > 0:
                cursor.execute("DELETE FROM reflex_drills WHERE drill_type = 'speed_translation';")

            reflex_builder = ReflexBuilder(sentence_pool=sentence_pool)
            reflex_count = 0
            for sent_dict in sentence_pool:
                if not sent_dict.get("text_vi") or not sent_dict["text_vi"].strip():
                    continue
                drill = reflex_builder.build_drill(sent_dict, drill_type="speed_translation")
                correct_ans = drill.get("correct_answer") if isinstance(drill, dict) else None
                if correct_ans is None or not str(correct_ans).strip():
                    continue
                cursor.execute("""
                    INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (drill["sentence_id"], drill["drill_type"], drill["prompt_text"], drill["correct_answer"], drill["distractors_json"], drill["target_time_ms"]))
                reflex_count += 1

                if reflex_count % 5000 == 0:
                    logger.info("   -> Generated %s reflex drill cards...", f"{reflex_count:,}")

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Failed to generate reflex drills: %s", e)
            raise e

        logger.info("[Step 6] Completed: %s reflex drill cards.", f"{reflex_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=reflex_count)

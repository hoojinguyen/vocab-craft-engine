import time
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.nlp.translator import Translator
from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)

VI_BATCH_SLEEP_SECONDS = 0.1
VI_TRANSLATION_BUDGET = 1000


class VietnameseBackfillStep(BaseStep):
    name = "vietnamese_backfill"
    description = "Validate & backfill Vietnamese translations with budget capping"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM definitions WHERE definition_vi IS NULL OR definition_vi = '';")
        def_missing = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        col_missing = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        phrase_missing = cursor.fetchone()[0]

        if (def_missing + col_missing + phrase_missing) == 0:
            return True, "No missing Vietnamese translations remain."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 12] Backfilling Vietnamese translations...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
        conn.commit()

        cursor.execute("""
            SELECT d.id, d.definition_en FROM definitions d
            JOIN words w ON w.id = d.word_id
            WHERE d.definition_vi IS NULL OR d.definition_vi = ''
            ORDER BY (w.cefr_level IS NULL), d.id;
        """)
        priority_definitions = cursor.fetchall()
        cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        priority_collocations = cursor.fetchall()
        cursor.execute("SELECT id, definition_en FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        priority_phrases = cursor.fetchall()

        translator = Translator()
        validator = VietnameseTextValidator()
        budget = getattr(context.args, "vi_budget", VI_TRANSLATION_BUDGET)

        colloc_budget = 0
        phrase_budget = 0
        defs_budget = 0
        if budget >= 3:
            small_table_slice = max(1, budget // 10)
            colloc_budget = min(len(priority_collocations), small_table_slice)
            phrase_budget = min(len(priority_phrases), small_table_slice)
            defs_budget = max(0, budget - colloc_budget - phrase_budget)
        elif budget > 0:
            colloc_budget = min(len(priority_collocations), budget)

        def _backfill(rows, table, id_col, target_col, remaining_budget):
            updated = 0
            for batch_start in range(0, len(rows), 1000):
                if remaining_budget <= 0:
                    break
                batch = rows[batch_start:batch_start + 1000]
                updates = []
                for row_id, text in batch:
                    if remaining_budget <= 0:
                        break
                    remaining_budget -= 1
                    vi = translator.translate_text(text)
                    if vi and validator.is_vietnamese(vi):
                        updates.append((vi, row_id))
                if updates:
                    cursor.executemany(f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?;", updates)
                    conn.commit()
                    updated += len(updates)
                time.sleep(VI_BATCH_SLEEP_SECONDS)
            return updated, remaining_budget

        translated_defs, _ = _backfill(priority_definitions, "definitions", "id", "definition_vi", defs_budget)
        translated_colls, _ = _backfill(priority_collocations, "collocations", "id", "meaning_vi", colloc_budget)
        translated_phrases, _ = _backfill(priority_phrases, "phrases", "id", "definition_vi", phrase_budget)

        logger.info("[Step 12] Completed: translated %s defs, %s colls, %s phrases.", f"{translated_defs:,}", f"{translated_colls:,}", f"{translated_phrases:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=translated_defs + translated_colls + translated_phrases)

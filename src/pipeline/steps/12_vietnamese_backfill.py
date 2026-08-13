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

    def _cleanup_passthrough(self, context: PipelineContext) -> None:
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
        cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
        conn.commit()

        validator = VietnameseTextValidator()

        cursor.execute("SELECT id, definition_vi FROM definitions WHERE definition_vi IS NOT NULL AND definition_vi != '';")
        bad_defs = [r[0] for r in cursor.fetchall() if not validator.is_vietnamese(r[1])]
        if bad_defs:
            cursor.executemany("UPDATE definitions SET definition_vi = NULL WHERE id = ?;", [(i,) for i in bad_defs])

        cursor.execute("SELECT id, meaning_vi FROM collocations WHERE meaning_vi IS NOT NULL AND meaning_vi != '';")
        bad_colls = [r[0] for r in cursor.fetchall() if not validator.is_vietnamese(r[1])]
        if bad_colls:
            cursor.executemany("UPDATE collocations SET meaning_vi = NULL WHERE id = ?;", [(i,) for i in bad_colls])

        cursor.execute("SELECT id, definition_vi FROM phrases WHERE definition_vi IS NOT NULL AND definition_vi != '';")
        bad_phrases = [r[0] for r in cursor.fetchall() if not validator.is_vietnamese(r[1])]
        if bad_phrases:
            cursor.executemany("UPDATE phrases SET definition_vi = NULL WHERE id = ?;", [(i,) for i in bad_phrases])

        conn.commit()

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            self._cleanup_passthrough(context)
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM definitions WHERE definition_vi IS NULL OR definition_vi = '' OR definition_vi = definition_en;"
            )
            def_missing = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '' OR meaning_vi = phrase;"
            )
            col_missing = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM phrases WHERE definition_vi IS NULL OR definition_vi = '' OR definition_vi = definition_en;"
            )
            phrase_missing = cursor.fetchone()[0]

            if (def_missing + col_missing + phrase_missing) == 0:
                return True, "No missing Vietnamese translations remain."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("Backfilling Vietnamese translations...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        self._cleanup_passthrough(context)

        cursor.execute("""
            SELECT count(*) FROM definitions d
            JOIN words w ON w.id = d.word_id
            WHERE d.definition_vi IS NULL OR d.definition_vi = '';
        """)
        row = cursor.fetchone()
        defs_count = row[0] if isinstance(row, (list, tuple)) and row else (row if isinstance(row, int) and not isinstance(row, bool) else 0)

        cursor.execute("SELECT count(*) FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
        row = cursor.fetchone()
        colloc_count = row[0] if isinstance(row, (list, tuple)) and row else (row if isinstance(row, int) and not isinstance(row, bool) else 0)

        cursor.execute("SELECT count(*) FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
        row = cursor.fetchone()
        phrase_count = row[0] if isinstance(row, (list, tuple)) and row else (row if isinstance(row, int) and not isinstance(row, bool) else 0)

        budget = getattr(context.args, "vi_budget", VI_TRANSLATION_BUDGET)

        colloc_budget = 0
        phrase_budget = 0
        defs_budget = 0
        if budget >= 3:
            small_table_slice = max(1, budget // 10)
            colloc_budget = min(colloc_count, small_table_slice)
            phrase_budget = min(phrase_count, small_table_slice)
            defs_budget = max(0, budget - colloc_budget - phrase_budget)
        elif budget > 0:
            colloc_budget = min(colloc_count, budget)

        priority_definitions = []
        if defs_budget > 0:
            cursor.execute("""
                SELECT d.id, d.definition_en FROM definitions d
                JOIN words w ON w.id = d.word_id
                WHERE d.definition_vi IS NULL OR d.definition_vi = ''
                ORDER BY (w.cefr_level IS NULL), d.id
                LIMIT ?;
            """, (defs_budget,))
            priority_definitions = cursor.fetchall()

        priority_collocations = []
        if colloc_budget > 0:
            cursor.execute("""
                SELECT id, phrase FROM collocations
                WHERE meaning_vi IS NULL OR meaning_vi = ''
                LIMIT ?;
            """, (colloc_budget,))
            priority_collocations = cursor.fetchall()

        priority_phrases = []
        if phrase_budget > 0:
            cursor.execute("""
                SELECT id, definition_en FROM phrases
                WHERE definition_vi IS NULL OR definition_vi = ''
                LIMIT ?;
            """, (phrase_budget,))
            priority_phrases = cursor.fetchall()

        translator = Translator()
        validator = VietnameseTextValidator()

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
                if hasattr(translator, "save_cache"):
                    translator.save_cache()
                time.sleep(VI_BATCH_SLEEP_SECONDS)
            return updated, remaining_budget

        translated_defs, _ = _backfill(priority_definitions, "definitions", "id", "definition_vi", defs_budget)
        if hasattr(translator, "save_cache"):
            translator.save_cache()
        translated_colls, _ = _backfill(priority_collocations, "collocations", "id", "meaning_vi", colloc_budget)
        if hasattr(translator, "save_cache"):
            translator.save_cache()
        translated_phrases, _ = _backfill(priority_phrases, "phrases", "id", "definition_vi", phrase_budget)
        if hasattr(translator, "save_cache"):
            translator.save_cache()

        logger.info("Completed: translated %s defs, %s colls, %s phrases.", f"{translated_defs:,}", f"{translated_colls:,}", f"{translated_phrases:,}")
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=translated_defs + translated_colls + translated_phrases,
            metrics={"definitions": translated_defs, "collocations": translated_colls, "phrases": translated_phrases}
        )


def run_vietnamese_step(db_manager, args) -> dict:
    step = VietnameseBackfillStep()
    context = PipelineContext(db_manager=db_manager, args=args)
    skip, _ = step.should_skip(context)
    if skip:
        return {"definitions": 0, "collocations": 0, "phrases": 0}
    res = step.run(context)
    return res.metrics if res.metrics else {"definitions": 0, "collocations": 0, "phrases": 0}

import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.media.ipa_mapper import IPAMapper

logger = logging.getLogger(__name__)


class IPAMappingStep(BaseStep):
    name = "ipa_mapping"
    description = "Populate missing UK/US IPA transcriptions"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM words WHERE COALESCE(TRIM(ipa_us), '') = '' OR COALESCE(TRIM(ipa_uk), '') = '';")
            missing = cursor.fetchone()[0]
            if missing == 0:
                return True, "100% of words already have IPA transcriptions."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 8] Mapping UK/US IPA transcriptions...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, lemma, ipa_uk, ipa_us FROM words WHERE COALESCE(TRIM(ipa_us), '') = '' OR COALESCE(TRIM(ipa_uk), '') = '';")
        rows = cursor.fetchall()

        ipa_mapper = IPAMapper()
        updated = 0
        for w_id, lemma, existing_uk, existing_us in rows:
            uk = ipa_mapper.get_ipa(lemma, existing_ipa=existing_uk)
            us = ipa_mapper.get_ipa(lemma, existing_ipa=existing_us)
            cursor.execute("UPDATE words SET ipa_uk = ?, ipa_us = ? WHERE id = ?;", (uk, us, w_id))
            updated += 1

        conn.commit()
        logger.info("[Step 8] Completed: updated IPA for %s words.", f"{updated:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=updated)

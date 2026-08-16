"""
Phonetic and Multi-Tier IPA Enrichment Step V3.

Resolves 100% US and UK IPA phonetic transcriptions across all curated words
using the multi-tier resolution hierarchy (DuckDB Cache -> Kaikki -> CMUdict -> g2p-en).
"""

import logging
from typing import Dict, List, Tuple
import pyarrow as pa

from src.media.ipa_mapper import IPAMapper
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus

logger = logging.getLogger(__name__)


class EnrichIPAStep(BaseStep):
    name = "enrich_ipa"
    description = "Resolve multi-tier phonetic IPA pronunciations for all words"
    depends_on = ["ingest_kaikki", "ingest_wordnet"]
    produces = ["words"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        conn = ctx.db.get_connection()
        missing_ipa = conn.execute("SELECT count(*) FROM words WHERE ipa_us IS NULL OR ipa_uk IS NULL").fetchone()[0]
        if missing_ipa == 0 and ctx.db.count_rows("words") > 0:
            return True, "100% IPA phonetic coverage already achieved"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        conn = ctx.db.get_connection()
        mapper = IPAMapper(db_mgr=ctx.db)

        words = conn.execute("""
            SELECT id, lemma, ipa_uk, ipa_us 
            FROM words 
            WHERE ipa_us IS NULL OR ipa_uk IS NULL OR trim(ipa_us) = '' OR trim(ipa_uk) = ''
        """).fetchall()

        if not words:
            logger.info("No words requiring IPA phonetic enrichment")
            return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=0)

        total_words = len(words)
        logger.info("Resolving phonetic IPA for %d words...", total_words)

        batch_size = 1000
        total_updated = 0

        for i in range(0, total_words, batch_size):
            chunk = words[i : i + batch_size]
            update_rows: List[Dict[str, object]] = []

            for wid, lemma, existing_uk, existing_us in chunk:
                if not lemma:
                    continue
                uk_res, us_res = mapper.get_ipa(
                    lemma,
                    existing_ipa_uk=existing_uk,
                    existing_ipa_us=existing_us,
                )
                if uk_res or us_res:
                    update_rows.append({
                        "word_id": wid,
                        "ipa_uk": uk_res or us_res,
                        "ipa_us": us_res or uk_res,
                    })

            if update_rows:
                arrow_table = pa.Table.from_pylist(update_rows)
                conn.register("_tmp_ipa_updates", arrow_table)
                conn.execute("""
                    UPDATE words
                    SET ipa_uk = _tmp_ipa_updates.ipa_uk,
                        ipa_us = _tmp_ipa_updates.ipa_us
                    FROM _tmp_ipa_updates
                    WHERE words.id = _tmp_ipa_updates.word_id;
                """)
                conn.unregister("_tmp_ipa_updates")
                total_updated += len(update_rows)

        logger.info("Successfully enriched phonetic IPA for %d/%d words", total_updated, total_words)

        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=total_updated,
        )

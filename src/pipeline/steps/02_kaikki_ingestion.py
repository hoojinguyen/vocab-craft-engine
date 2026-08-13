import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH, KAIKKI_INGEST_CHECKPOINT
from src.ingestion.kaikki_parser import KaikkiParser
from src.nlp.cefr_grader import CEFRGrader
from src.media.ipa_mapper import IPAMapper

logger = logging.getLogger(__name__)

class KaikkiIngestionStep(BaseStep):
    name = "kaikki_ingestion"
    description = "Ingest Kaikki Wiktionary JSON dump (3.18 GB)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "skip_dict", False):
            return True, "--skip-dict flag active"
        if getattr(context.args, "force_reset", False):
            return False, ""

        if KAIKKI_INGEST_CHECKPOINT.exists():
            return True, "CHECKPOINT DETECTED: Kaikki Wiktionary ingestion previously completed."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 2] Ingesting Kaikki Dictionary...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        ipa_mapper = IPAMapper()
        kaikki_parser = KaikkiParser(KAIKKI_JSON_PATH)

        words_batch = []
        pending_items_batch = []
        definitions_batch = []
        count = 0
        words_count = 0
        definitions_count = 0

        for item in kaikki_parser.parse_stream():
            count += 1
            lemma = item["lemma"]
            pos = item["pos"]
            ipa_uk = item["ipa_uk"]
            ipa_us = item["ipa_us"]

            final_ipa_us = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_us)
            final_ipa_uk = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_uk)
            cefr_lvl, freq_rank = grader.grade_word(lemma)

            words_batch.append({
                "lemma": lemma,
                "pos": pos,
                "ipa_uk": final_ipa_uk,
                "ipa_us": final_ipa_us,
                "frequency_rank": freq_rank,
                "cefr_level": cefr_lvl
            })
            pending_items_batch.append(item)

            if len(words_batch) >= 5000:
                words_inserted = context.db_manager.insert_words_batch(words_batch)
                words_count += words_inserted if isinstance(words_inserted, int) else len(words_batch)
                words_batch = []

                for p_item in pending_items_batch:
                    word_id = context.db_manager.get_word_id_by_lemma(p_item["lemma"])
                    if word_id:
                        for def_item in p_item.get("definitions", []):
                            definitions_batch.append({
                                "word_id": word_id,
                                "definition_en": def_item["definition_en"],
                                "definition_vi": def_item.get("definition_vi"),
                                "example": def_item.get("example"),
                                "source": def_item["source"]
                            })

                            if len(definitions_batch) >= 5000:
                                defs_inserted = context.db_manager.insert_definitions_batch(definitions_batch)
                                definitions_count += defs_inserted if isinstance(defs_inserted, int) else len(definitions_batch)
                                definitions_batch = []
                pending_items_batch = []

            if count % 50000 == 0:
                logger.info("   -> Processed %s dictionary entries (%s words, %s defs stored)...",
                            f"{count:,}", f"{words_count:,}", f"{definitions_count:,}")

        if words_batch:
            words_inserted = context.db_manager.insert_words_batch(words_batch)
            words_count += words_inserted if isinstance(words_inserted, int) else len(words_batch)
            words_batch = []

            for p_item in pending_items_batch:
                word_id = context.db_manager.get_word_id_by_lemma(p_item["lemma"])
                if word_id:
                    for def_item in p_item.get("definitions", []):
                        definitions_batch.append({
                            "word_id": word_id,
                            "definition_en": def_item["definition_en"],
                            "definition_vi": def_item.get("definition_vi"),
                            "example": def_item.get("example"),
                            "source": def_item["source"]
                        })

                        if len(definitions_batch) >= 5000:
                            defs_inserted = context.db_manager.insert_definitions_batch(definitions_batch)
                            definitions_count += defs_inserted if isinstance(defs_inserted, int) else len(definitions_batch)
                            definitions_batch = []
            pending_items_batch = []

        if definitions_batch:
            defs_inserted = context.db_manager.insert_definitions_batch(definitions_batch)
            definitions_count += defs_inserted if isinstance(defs_inserted, int) else len(definitions_batch)
            definitions_batch = []

        KAIKKI_INGEST_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        KAIKKI_INGEST_CHECKPOINT.touch()

        total_items = words_count + definitions_count
        logger.info("[Step 2] Completed: %s words, %s definitions stored.", f"{words_count:,}", f"{definitions_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=total_items)

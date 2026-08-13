import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH
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

        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM words;")
            existing_words = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM definitions;")
            existing_defs = cursor.fetchone()[0]

            if existing_words > 10000 and existing_defs > 10000:
                return True, f"CHECKPOINT DETECTED: {existing_words:,} words & {existing_defs:,} definitions exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 2] Ingesting Kaikki Dictionary...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        ipa_mapper = IPAMapper()
        kaikki_parser = KaikkiParser(KAIKKI_JSON_PATH)

        words_batch = []
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

            if len(words_batch) >= 5000:
                context.db_manager.insert_words_batch(words_batch)
                words_count += len(words_batch)
                words_batch = []

            if count % 50000 == 0:
                logger.info("   -> Processed %s dictionary entries (%s words staged)...", f"{count:,}", f"{words_count:,}")

        if words_batch:
            context.db_manager.insert_words_batch(words_batch)
            words_count += len(words_batch)

        logger.info("   -> Extracting definitions...")
        def_stream_count = 0
        for item in kaikki_parser.parse_stream():
            def_stream_count += 1
            word_id = context.db_manager.get_word_id_by_lemma(item["lemma"])
            if word_id:
                for def_item in item["definitions"]:
                    definitions_batch.append({
                        "word_id": word_id,
                        "definition_en": def_item["definition_en"],
                        "definition_vi": def_item.get("definition_vi"),
                        "example": def_item.get("example"),
                        "source": def_item["source"]
                    })

                    if len(definitions_batch) >= 5000:
                        context.db_manager.insert_definitions_batch(definitions_batch)
                        definitions_count += len(definitions_batch)
                        definitions_batch = []

            if def_stream_count % 100000 == 0:
                logger.info("   -> Staged %s definitions...", f"{definitions_count:,}")

        if definitions_batch:
            context.db_manager.insert_definitions_batch(definitions_batch)
            definitions_count += len(definitions_batch)

        logger.info("[Step 2] Completed: %s words, %s definitions stored.", f"{words_count:,}", f"{definitions_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=words_count + definitions_count)

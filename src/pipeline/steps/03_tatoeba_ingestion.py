import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.tatoeba_parser import TatoebaParser
from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)

class TatoebaIngestionStep(BaseStep):
    name = "tatoeba_ingestion"
    description = "Ingest Tatoeba aligned parallel sentences"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sentences;")
            existing_sentences = cursor.fetchone()[0]
            if existing_sentences > 1000:
                return True, f"CHECKPOINT DETECTED: {existing_sentences:,} sentence pairs exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 3] Ingesting Tatoeba Parallel Sentences...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        tatoeba_parser = TatoebaParser(TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH)
        sentences_batch = []
        sent_count = 0

        for pair in tatoeba_parser.parse_aligned_pairs():
            graded = grader.grade_sentence(pair["text_en"])
            sentences_batch.append({
                "text_en": pair["text_en"],
                "text_vi": pair["text_vi"],
                "difficulty_score": graded["difficulty_score"],
                "cefr_level": graded["cefr_level"],
                "audio_path": f"sent_{sent_count + len(sentences_batch)}_std.mp3",
                "source": pair["source"]
            })

            if len(sentences_batch) >= 5000:
                context.db_manager.insert_sentences_batch(sentences_batch)
                sent_count += len(sentences_batch)
                sentences_batch = []
                logger.info("   -> Staged %s aligned sentence pairs...", f"{sent_count:,}")

        if sentences_batch:
            context.db_manager.insert_sentences_batch(sentences_batch)
            sent_count += len(sentences_batch)

        logger.info("[Step 3] Completed: %s sentence pairs stored.", f"{sent_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=sent_count)

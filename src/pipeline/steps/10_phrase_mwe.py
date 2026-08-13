import asyncio
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH
from src.ingestion.phrase_parser import PhraseParser
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.phrase_grader import PhraseGrader
from src.nlp.phrase_example_matcher import PhraseExampleMatcher
from src.nlp.translator import Translator
from src.media.audio_generator import AudioGenerator

logger = logging.getLogger(__name__)


class PhraseMWEStep(BaseStep):
    name = "phrase_mwe"
    description = "Ingest Multi-Word Expressions (idioms, phrasal verbs, proverbs)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM phrases;")
        existing_phrases = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM phrases WHERE audio_std IS NULL OR audio_fast IS NULL;")
        missing_audio = cursor.fetchone()[0]

        if existing_phrases > 500 and missing_audio == 0:
            return True, f"CHECKPOINT DETECTED: {existing_phrases:,} phrases with complete audio already exist."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 10] Ingesting Multi-Word Expressions...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        phrase_parser = PhraseParser(KAIKKI_JSON_PATH)
        grader = PhraseGrader(CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH))
        translator = Translator()

        phrases_batch = []
        phrase_count = 0
        for item in phrase_parser.parse_phrases():
            graded = grader.grade_phrase(item["phrase"])
            phrases_batch.append({
                "phrase": item["phrase"],
                "phrase_type": item["phrase_type"],
                "pos": item["pos"],
                "cefr_level": graded["cefr_level"],
                "difficulty_score": graded["difficulty_score"],
                "definition_en": item["definition_en"],
                "definition_vi": item.get("definition_vi") or translator.translate_text(item["phrase"]),
                "ipa": item.get("ipa"),
                "audio_std": None,
                "audio_fast": None,
                "audio_status": "ok"
            })

            if len(phrases_batch) >= 1000:
                context.db_manager.insert_phrases_batch(phrases_batch)
                phrase_count += len(phrases_batch)
                phrases_batch = []

        if phrases_batch:
            context.db_manager.insert_phrases_batch(phrases_batch)
            phrase_count += len(phrases_batch)

        cursor.execute("SELECT id, text_en, cefr_level FROM sentences;")
        sentence_pool = [{"id": r[0], "text_en": r[1], "cefr_level": r[2]} for r in cursor.fetchall()]
        matcher = PhraseExampleMatcher(sentence_pool)

        cursor.execute("SELECT id, phrase FROM phrases;")
        stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
        link_batch = matcher.match_phrases(stored_phrases)
        for i in range(0, len(link_batch), 5000):
            context.db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])

        async def generate_phrase_audio():
            audio_gen = AudioGenerator()
            for i in range(0, len(stored_phrases), 10):
                chunk = stored_phrases[i:i + 10]
                results = await asyncio.gather(
                    *[audio_gen.generate_dual_speed_phrase(item["id"], item["phrase"]) for item in chunk]
                )
                updates = []
                for item, res in zip(chunk, results):
                    status = "ok" if res["standard_path"] and res["fast_path"] else "failed"
                    updates.append((
                        str(res["standard_path"]) if res["standard_path"] else None,
                        str(res["fast_path"]) if res["fast_path"] else None,
                        status,
                        item["id"]
                    ))
                cursor.executemany("UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;", updates)
                conn.commit()

        try:
            asyncio.run(generate_phrase_audio())
        except Exception as e:
            logger.warning("   [Step 10] Phrase audio warning: %s", e)

        logger.info("[Step 10] Completed: %s phrases stored, %s links.", f"{phrase_count:,}", f"{len(link_batch):,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=phrase_count)

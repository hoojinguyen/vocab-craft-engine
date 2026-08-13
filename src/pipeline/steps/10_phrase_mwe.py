from pathlib import Path
import asyncio
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH, SUBTLEX_FREQ_PATH, AUDIO_DIR
from src.ingestion.phrase_parser import PhraseParser
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.phrase_grader import PhraseGrader
from src.nlp.phrase_example_matcher import PhraseExampleMatcher
from src.nlp.translator import Translator
from src.media.audio_generator import AudioGenerator

logger = logging.getLogger(__name__)


def _audio_file_valid(path_str) -> bool:
    if not path_str or not isinstance(path_str, (str, Path)):
        return False
    p = Path(path_str)
    try:
        if p.is_file() and p.stat().st_size > 0:
            return True
        p_audio = AUDIO_DIR / path_str
        if p_audio.is_file() and p_audio.stat().st_size > 0:
            return True
    except Exception:
        pass
    return False


class PhraseMWEStep(BaseStep):
    name = "phrase_mwe"
    description = "Ingest Multi-Word Expressions (idioms, phrasal verbs, proverbs)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM phrases;")
            row = cursor.fetchone()
            existing_phrases = row[0] if row else 0

            cursor.execute("SELECT audio_std, audio_fast FROM phrases;")
            audio_rows = cursor.fetchall()

            if existing_phrases > 500 and audio_rows:
                missing_audio = sum(
                    1 for std, fast in audio_rows if not _audio_file_valid(std) or not _audio_file_valid(fast)
                )
                if missing_audio == 0:
                    return True, f"CHECKPOINT DETECTED: {existing_phrases:,} phrases with complete audio already exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 10] Ingesting Multi-Word Expressions...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT count(*) FROM phrases;")
        row = cursor.fetchone()
        existing_phrases = row[0] if (row and isinstance(row[0], (int, float))) else 0

        if existing_phrases > 500:
            logger.info("   [Step 10] Found %d existing phrases (>500), skipping Kaikki file parsing.", existing_phrases)
            phrase_count = existing_phrases
        else:
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
                    inserted = context.db_manager.insert_phrases_batch(phrases_batch)
                    phrase_count += inserted if isinstance(inserted, int) else len(phrases_batch)
                    phrases_batch = []

            if phrases_batch:
                inserted = context.db_manager.insert_phrases_batch(phrases_batch)
                phrase_count += inserted if isinstance(inserted, int) else len(phrases_batch)

            if hasattr(translator, "save_cache"):
                translator.save_cache()

        cursor.execute("SELECT id, text_en, cefr_level FROM sentences;")
        sentence_pool = []
        while True:
            rows = cursor.fetchmany(10000)
            if not isinstance(rows, (list, tuple)):
                rows = cursor.fetchall()
                if isinstance(rows, (list, tuple)):
                    sentence_pool.extend([{"id": r[0], "text_en": r[1], "cefr_level": r[2]} for r in rows])
                break
            if not rows:
                break
            sentence_pool.extend([{"id": r[0], "text_en": r[1], "cefr_level": r[2]} for r in rows])

        matcher = PhraseExampleMatcher(sentence_pool)

        cursor.execute("SELECT id, phrase FROM phrases;")
        stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
        link_batch = matcher.match_phrases(stored_phrases)
        for i in range(0, len(link_batch), 5000):
            context.db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])

        def _to_relative_path(path_obj, base_dir):
            if not path_obj:
                return None
            p = Path(path_obj)
            if not p.is_absolute():
                return str(p)
            try:
                return str(p.relative_to(Path.cwd()))
            except ValueError:
                pass
            try:
                return str(p.relative_to(base_dir))
            except ValueError:
                pass
            return p.name

        async def generate_phrase_audio():
            audio_gen = AudioGenerator()
            any_failed = False
            for i in range(0, len(stored_phrases), 10):
                chunk = stored_phrases[i:i + 10]
                results = await asyncio.gather(
                    *[audio_gen.generate_dual_speed_phrase(item["id"], item["phrase"]) for item in chunk]
                )
                updates = []
                for item, res in zip(chunk, results):
                    status = "ok" if res["standard_path"] and res["fast_path"] else "failed"
                    if status == "failed":
                        any_failed = True
                    updates.append((
                        _to_relative_path(res["standard_path"], audio_gen.output_dir),
                        _to_relative_path(res["fast_path"], audio_gen.output_dir),
                        status,
                        item["id"]
                    ))
                cursor.executemany("UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;", updates)
                conn.commit()

            if any_failed:
                raise RuntimeError("Phrase audio generation failed for one or more phrases.")

        try:
            asyncio.run(generate_phrase_audio())
        except Exception as e:
            logger.error("   [Step 10] Phrase audio generation error: %s", e)
            return StepResult(step_name=self.name, status=StepStatus.FAILED, items_processed=phrase_count, error=e, message=str(e))

        logger.info("[Step 10] Completed: %s phrases stored, %s links.", f"{phrase_count:,}", f"{len(link_batch):,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=phrase_count)


def run_phrase_step(db_manager, args) -> dict:
    step = PhraseMWEStep()
    context = PipelineContext(db_manager=db_manager, args=args)
    skip, _ = step.should_skip(context)
    if skip:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM phrases;")
        phrases = cursor.fetchone()[0]
        return {"phrases": phrases, "links": 0}
    res = step.run(context)
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM phrase_sentences;")
    links = cursor.fetchone()[0]
    return {"phrases": res.items_processed, "links": links}


import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
import config.settings as settings
from src.ingestion.opus_parser import ParallelCorpusParser
from src.ingestion.sentence_filter import SentenceFilter
from src.nlp.cefr_grader import CEFRGrader

logger = logging.getLogger(__name__)


class SentenceCoverageStep(BaseStep):
    name = "sentence_coverage"
    description = "Ingest OPUS & EnViCorpora parallel sentence coverage"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        corpora = [
            (settings.OPENSUBTITLES_EN, settings.OPENSUBTITLES_VI, "OpenSubtitles"),
            (settings.ENVICORPORA_TED_LIKE_EN, settings.ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
            (settings.ENVICORPORA_BASIC_EN, settings.ENVICORPORA_BASIC_VI, "Basic-EnVi"),
        ]
        max_sentences = settings.MAX_SENTENCES_PER_CORPUS
        all_skipped = True
        try:
            for en_path, vi_path, source in corpora:
                if not en_path.exists() or not vi_path.exists():
                    continue
                existing = context.db_manager.count_sentences_by_source(source)
                if existing < max_sentences:
                    all_skipped = False
                    break
            if all_skipped:
                return True, "All parallel sentence corpora already ingested."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 14] Ingesting Sentence Coverage Parallel Corpora...")
        corpora = [
            (settings.OPENSUBTITLES_EN, settings.OPENSUBTITLES_VI, "OpenSubtitles"),
            (settings.ENVICORPORA_TED_LIKE_EN, settings.ENVICORPORA_TED_LIKE_VI, "TED-EnVi"),
            (settings.ENVICORPORA_BASIC_EN, settings.ENVICORPORA_BASIC_VI, "Basic-EnVi"),
        ]
        sf = SentenceFilter()
        grader = CEFRGrader(subtlex_path=settings.SUBTLEX_FREQ_PATH)
        max_sentences = settings.MAX_SENTENCES_PER_CORPUS

        inserted_total = 0
        for en_path, vi_path, source in corpora:
            if not en_path.exists() or not vi_path.exists():
                logger.info("   [SentenceCoverage] %s corpus missing — skipping.", source)
                continue

            if getattr(context.args, "force_reset", False):
                conn = context.db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sentences WHERE source = ?;", (source,))
                conn.commit()

            existing = context.db_manager.count_sentences_by_source(source)
            if existing >= max_sentences and not getattr(context.args, "force_reset", False):
                logger.info(
                    "   [SentenceCoverage] %s already ingested (%s rows) — skipping.",
                    source,
                    f"{existing:,}",
                )
                continue

            batch = []
            accepted_candidates = 0
            corpus_inserted = 0
            for pair in ParallelCorpusParser(en_path, vi_path, source=source).parse_pairs():
                if accepted_candidates + len(batch) >= max_sentences:
                    break
                if not sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
                    continue
                graded = grader.grade_sentence(pair["text_en"])
                batch.append({
                    "text_en": pair["text_en"],
                    "text_vi": pair["text_vi"],
                    "difficulty_score": graded["difficulty_score"],
                    "cefr_level": graded["cefr_level"],
                    "audio_path": None,
                    "source": source,
                })
                if len(batch) >= 5000:
                    rows_inserted = context.db_manager.insert_sentences_batch(batch)
                    if isinstance(rows_inserted, int) and not isinstance(rows_inserted, bool):
                        corpus_inserted += rows_inserted
                    else:
                        corpus_inserted += len(batch)
                    accepted_candidates += len(batch)
                    batch = []
            if batch:
                rows_inserted = context.db_manager.insert_sentences_batch(batch)
                if isinstance(rows_inserted, int) and not isinstance(rows_inserted, bool):
                    corpus_inserted += rows_inserted
                else:
                    corpus_inserted += len(batch)
                accepted_candidates += len(batch)
                batch = []
            inserted_total += corpus_inserted

        logger.info("[Step 14] Completed: %s new sentences inserted.", f"{inserted_total:,}")
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=inserted_total,
        )


def run_sentence_coverage_step(db_manager, args) -> dict:
    step = SentenceCoverageStep()
    context = PipelineContext(db_manager=db_manager, args=args)
    res = step.run(context)
    return {"inserted": res.items_processed}

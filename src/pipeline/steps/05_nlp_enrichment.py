import json
import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import SUBTLEX_FREQ_PATH
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.chunk_extractor import ChunkExtractor
from src.nlp.translator import Translator

logger = logging.getLogger(__name__)

EXPECTED_PATTERN_NAMES = {
    "Subject + Verb + Object",
    "Subject + Verb + Prepositional Phrase",
    "Subject + Auxiliary + Verb + Object"
}


class NLPEnrichmentStep(BaseStep):
    name = "nlp_enrichment"
    description = "Extract collocations and populate sentence patterns"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM collocations;")
            existing_collocs = cursor.fetchone()[0]
            cursor.execute("SELECT pattern_name FROM sentence_patterns;")
            existing_patterns = {row[0] for row in cursor.fetchall()}
            if existing_collocs > 500 and EXPECTED_PATTERN_NAMES.issubset(existing_patterns):
                return True, f"CHECKPOINT DETECTED: {existing_collocs:,} collocations exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("Running NLP Enrichment...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, text_en FROM sentences;")
        all_sentences = cursor.fetchall()
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        chunk_extractor = ChunkExtractor()
        translator = Translator()

        colloc_batch = []
        colloc_inserted = 0
        seen_phrases = set()
        for s_id, text_en in all_sentences:
            chunks = chunk_extractor.extract_collocations(text_en)
            for chunk in chunks:
                phrase = chunk["phrase"]
                if phrase not in seen_phrases:
                    seen_phrases.add(phrase)
                    c_level, _ = grader.grade_word(phrase.split()[0] if phrase else "the")
                    colloc_batch.append({
                        "phrase": phrase,
                        "meaning_vi": translator.translate_text(phrase),
                        "pos_pattern": chunk["pos_pattern"],
                        "cefr_level": c_level if c_level in ("A1", "A2", "B1", "B2", "C1", "C2") else "B1"
                    })

                if len(colloc_batch) >= 1000:
                    colloc_inserted += context.db_manager.insert_collocations_batch(colloc_batch)
                    colloc_batch = []

        if colloc_batch:
            colloc_inserted += context.db_manager.insert_collocations_batch(colloc_batch)

        if hasattr(translator, "save_cache"):
            translator.save_cache()

        patterns = [
            {"pattern_name": "Subject + Verb + Object", "structure_json": json.dumps(["NP", "VP", "NP"]), "example_en": "She drinks hot coffee.", "example_vi": "Cô ấy uống cà phê nóng.", "cefr_level": "A1"},
            {"pattern_name": "Subject + Verb + Prepositional Phrase", "structure_json": json.dumps(["NP", "VP", "PP"]), "example_en": "They run in the park.", "example_vi": "Họ chạy trong công viên.", "cefr_level": "A2"},
            {"pattern_name": "Subject + Auxiliary + Verb + Object", "structure_json": json.dumps(["NP", "AUX", "VP", "NP"]), "example_en": "I can learn English.", "example_vi": "Tôi có thể học tiếng Anh.", "cefr_level": "B1"}
        ]
        patterns_count = context.db_manager.insert_sentence_patterns_batch(patterns)

        logger.info("Completed: %s collocations, %s sentence patterns.", f"{colloc_inserted:,}", patterns_count)
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=colloc_inserted + patterns_count)

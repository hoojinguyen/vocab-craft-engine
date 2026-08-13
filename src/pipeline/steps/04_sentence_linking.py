import json
import logging
from pathlib import Path
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import SENTENCE_LINK_CHECKPOINT
from src.nlp.lemmatizer import Lemmatizer

logger = logging.getLogger(__name__)

class SentenceLinkingStep(BaseStep):
    name = "sentence_linking"
    description = "Incremental word-sentence mapping and lemmatization"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Always run incrementally; if no new sentences exist, zero rows will be processed.
        return False, ""

    def _read_checkpoint(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return int(json.loads(path.read_text(encoding="utf-8"))["last_id"])
        except Exception:
            return 0

    def _write_checkpoint(self, path: Path, last_id: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_id": last_id}), encoding="utf-8")

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 4] Linking Word-Sentence Mappings (incremental)...")
        last_linked = self._read_checkpoint(SENTENCE_LINK_CHECKPOINT)
        lemmatizer = Lemmatizer()
        map_batch = []
        new_max = last_linked
        cursor = context.db_manager.get_connection().cursor()
        cursor.execute("SELECT id, text_en FROM sentences WHERE id > ? ORDER BY id;", (last_linked,))

        linked_count = 0
        for s_id, text_en in cursor.fetchall():
            lemmas = lemmatizer.lemmatize_text(text_en)
            for lem in lemmas:
                word_id = context.db_manager.get_word_id_by_lemma(lem["lemma"])
                if word_id:
                    map_batch.append({"word_id": word_id, "sentence_id": s_id})
                    linked_count += 1
            new_max = max(new_max, s_id)
            if len(map_batch) >= 5000:
                context.db_manager.insert_word_sentence_map_batch(map_batch)
                map_batch = []

        if map_batch:
            context.db_manager.insert_word_sentence_map_batch(map_batch)

        if new_max > last_linked:
            self._write_checkpoint(SENTENCE_LINK_CHECKPOINT, new_max)

        logger.info("[Step 4] Linked sentences to %s word links.", f"{linked_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=linked_count)

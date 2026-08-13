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

def _read_sentence_link_checkpoint(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["last_id"])
    except Exception:
        return 0


def _write_sentence_link_checkpoint(path: Path, last_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_id": last_id}), encoding="utf-8")


def _clear_sentence_link_checkpoint() -> None:
    SENTENCE_LINK_CHECKPOINT.unlink(missing_ok=True)


def _link_sentences_incrementally(db_manager, checkpoint: Path, batch_size: int = 5000) -> int:
    last_linked = _read_sentence_link_checkpoint(checkpoint)
    lemmatizer = None
    map_batch = []
    new_max = last_linked
    total_inserted = 0

    cursor = db_manager.get_connection().cursor()
    cursor.execute("SELECT id, text_en FROM sentences WHERE id > ? ORDER BY id;", (last_linked,))

    while True:
        rows = cursor.fetchmany(batch_size)
        if not isinstance(rows, (list, tuple)):
            rows = cursor.fetchall()
            is_mock_fallback = True
        else:
            is_mock_fallback = False

        if not rows:
            break

        if lemmatizer is None:
            lemmatizer = Lemmatizer()

        for s_id, text_en in rows:
            lemmas = lemmatizer.lemmatize_text(text_en)
            seen_word_ids = set()
            for lem in lemmas:
                word_id = db_manager.get_word_id_by_lemma(lem["lemma"])
                if word_id and word_id not in seen_word_ids:
                    seen_word_ids.add(word_id)
                    map_batch.append({"word_id": word_id, "sentence_id": s_id})
            new_max = max(new_max, s_id)

            if len(map_batch) >= batch_size:
                inserted = db_manager.insert_word_sentence_map_batch(map_batch)
                total_inserted += inserted if isinstance(inserted, int) else len(map_batch)
                map_batch = []

        if is_mock_fallback:
            break

    if map_batch:
        inserted = db_manager.insert_word_sentence_map_batch(map_batch)
        total_inserted += inserted if isinstance(inserted, int) else len(map_batch)

    if new_max > last_linked:
        _write_sentence_link_checkpoint(checkpoint, new_max)

    return total_inserted


class SentenceLinkingStep(BaseStep):
    name = "sentence_linking"
    description = "Incremental word-sentence mapping and lemmatization"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        # Always run incrementally; if no new sentences exist, zero rows will be processed.
        return False, ""

    def _read_checkpoint(self, path: Path) -> int:
        return _read_sentence_link_checkpoint(path)

    def _write_checkpoint(self, path: Path, last_id: int) -> None:
        _write_sentence_link_checkpoint(path, last_id)

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 4] Linking Word-Sentence Mappings (incremental)...")
        linked_count = _link_sentences_incrementally(context.db_manager, SENTENCE_LINK_CHECKPOINT)
        logger.info("[Step 4] Linked sentences to %s word links.", f"{linked_count:,}")
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=linked_count)


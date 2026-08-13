import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import KAIKKI_JSON_PATH
from src.ingestion.relation_parser import RelationParser

logger = logging.getLogger(__name__)

RELATION_CHECKPOINT = 50_000
TOPIC_CHECKPOINT = 1_000


class RelationsTopicsStep(BaseStep):
    name = "relations_topics"
    description = "Extract lexical relations (synonyms, antonyms) and 18 topic themes"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if getattr(context.args, "force_reset", False):
            return False, ""
        try:
            conn = context.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM word_relations;")
            existing_relations = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM word_topics;")
            existing_topics = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM word_relations WHERE relation_type = 'hyponym' AND inverted = 1;")
            existing_inverse = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM word_relations WHERE relation_type = 'hypernym' AND inverted = 0 AND target_word_id IS NOT NULL;")
            natural_hypernyms = cursor.fetchone()[0]

            if (
                existing_relations > RELATION_CHECKPOINT
                and existing_topics > TOPIC_CHECKPOINT
                and natural_hypernyms > 0
                and existing_inverse >= natural_hypernyms
            ):
                return True, f"CHECKPOINT DETECTED: {existing_relations:,} relations, {existing_topics:,} topics exist."
        except Exception:
            pass
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("Building Lexical Relations & Topics...")
        conn = context.db_manager.get_connection()
        cursor = conn.cursor()

        relation_parser = RelationParser(KAIKKI_JSON_PATH)
        cursor.execute("SELECT id, lemma FROM words;")
        lemma_map = {lemma: word_id for word_id, lemma in cursor.fetchall()}

        relations_batch = []
        topics_batch = []
        relation_count = 0
        topics_count = 0

        for item in relation_parser.parse_entries():
            word_id = lemma_map.get(item["word"])
            if word_id is None:
                continue
            for rel in item["relations"]:
                relations_batch.append({
                    "word_id": word_id,
                    "relation_type": rel["relation_type"],
                    "target_text": rel["target"],
                    "target_word_id": lemma_map.get(rel["target"]),
                    "inverted": 0,
                    "source": rel["source"]
                })
                if len(relations_batch) >= 1000:
                    inserted = context.db_manager.insert_word_relations_batch(relations_batch)
                    relation_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0
                    relations_batch = []
            for top in item["topics"]:
                topics_batch.append({"word_id": word_id, "topic": top["topic"], "raw_topic": top["raw_topic"]})
                if len(topics_batch) >= 1000:
                    inserted = context.db_manager.insert_word_topics_batch(topics_batch)
                    topics_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0
                    topics_batch = []

        if relations_batch:
            inserted = context.db_manager.insert_word_relations_batch(relations_batch)
            relation_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0
        if topics_batch:
            inserted = context.db_manager.insert_word_topics_batch(topics_batch)
            topics_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0

        cursor.execute("""
            SELECT wr.word_id, w.lemma, wr.target_word_id, wr.source
            FROM word_relations wr
            JOIN words w ON w.id = wr.word_id
            WHERE wr.relation_type = 'hypernym' AND wr.inverted = 0 AND wr.target_word_id IS NOT NULL;
        """)
        natural_hypernyms = cursor.fetchall()
        inverse_batch = []
        link_count = 0
        for word_id, lemma, target_word_id, source in natural_hypernyms:
            inverse_batch.append({
                "word_id": target_word_id,
                "relation_type": "hyponym",
                "target_text": lemma,
                "target_word_id": word_id,
                "inverted": 1,
                "source": source
            })
            if len(inverse_batch) >= 5000:
                inserted = context.db_manager.insert_word_relations_batch(inverse_batch)
                link_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0
                inverse_batch = []
        if inverse_batch:
            inserted = context.db_manager.insert_word_relations_batch(inverse_batch)
            link_count += inserted if isinstance(inserted, int) and inserted >= 0 else 0

        logger.info("Completed: %s relations, %s inverse links, %s topics.", f"{relation_count:,}", f"{link_count:,}", f"{topics_count:,}")
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=relation_count + topics_count + link_count,
            metrics={"relations": relation_count, "links": link_count, "topics": topics_count}
        )


def run_relations_step(db_manager, args) -> dict:
    step = RelationsTopicsStep()
    context = PipelineContext(db_manager=db_manager, args=args)
    skip, _ = step.should_skip(context)
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    if skip:
        cursor.execute("SELECT count(*) FROM word_relations;")
        relations = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM word_topics;")
        topics = cursor.fetchone()[0]
        return {"relations": relations, "links": 0, "topics": topics}
    res = step.run(context)
    return res.metrics

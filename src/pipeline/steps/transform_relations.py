"""Relations and Topics Transform Step V2."""

from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from src.transform.relation_builder import RelationBuilder
from src.transform.topic_mapper import TopicMapper


class TransformRelationsStep(BaseStep):
    name = "transform_relations"
    description = "Deduplicate lexical relations and map word topics"
    depends_on = ["ingest_kaikki", "ingest_wordnet"]
    produces = ["word_relations", "word_topics"]
    execution_type = "cpu"

    def should_skip(self, ctx: PipelineContext) -> Tuple[bool, str]:
        count = ctx.db.count_rows("word_topics")
        if count > 0:
            return True, f"Word topics present ({count})"
        return False, ""

    def run(self, ctx: PipelineContext) -> StepResult:
        rel_builder = RelationBuilder()
        rel_builder.deduplicate(ctx.db)

        mapper = TopicMapper()
        count = mapper.map_topics(ctx.db)

        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=count)

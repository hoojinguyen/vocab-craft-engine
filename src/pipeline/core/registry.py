"""Pipeline Step Registry V2."""

import logging
from typing import List, Optional
from src.pipeline.core.base_step import BaseStep
from src.pipeline.steps.schema_init import SchemaInitStep
from src.pipeline.steps.ingest_kaikki import IngestKaikkiStep
from src.pipeline.steps.ingest_tatoeba import IngestTatoebaStep
from src.pipeline.steps.ingest_opus import IngestOpusStep
from src.pipeline.steps.ingest_wordnet import IngestWordNetStep
from src.pipeline.steps.transform_linking import TransformLinkingStep
from src.pipeline.steps.transform_phrases import TransformPhrasesStep
from src.pipeline.steps.transform_relations import TransformRelationsStep
from src.pipeline.steps.enrich_ipa import EnrichIPAStep
from src.pipeline.steps.enrich_translation import EnrichTranslationStep
from src.pipeline.steps.enrich_reflex import EnrichReflexStep
from src.pipeline.steps.enrich_scenarios import EnrichScenariosStep
from src.pipeline.steps.enrich_audio import EnrichAudioStep
from src.pipeline.steps.export_sqlite import ExportSQLiteStep
from src.pipeline.steps.export_core3000 import ExportCore3000Step
from src.pipeline.steps.export_json import ExportJsonStep

logger = logging.getLogger(__name__)


class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []
        self._step_map: dict[str, BaseStep] = {}

    def register(self, step: BaseStep) -> None:
        if step.name in self._step_map:
            raise ValueError(f"Step with name '{step.name}' is already registered.")
        self._steps.append(step)
        self._step_map[step.name] = step

    def get_steps(self) -> List[BaseStep]:
        return list(self._steps)

    def get_step(self, name: str) -> Optional[BaseStep]:
        return self._step_map.get(name)

    def filter_steps(
        self, include_steps: Optional[List[str]] = None, skip_steps: Optional[List[str]] = None
    ) -> List[BaseStep]:
        if include_steps:
            for name in include_steps:
                if name not in self._step_map:
                    raise ValueError(f"Unknown step name '{name}'")
        if skip_steps:
            for name in skip_steps:
                if name not in self._step_map:
                    raise ValueError(f"Unknown step name '{name}'")

        result = []
        for step in self._steps:
            if include_steps and step.name not in include_steps:
                continue
            if skip_steps and step.name in skip_steps:
                continue
            result.append(step)
        return result


def get_default_registry() -> StepRegistry:
    registry = StepRegistry()
    registry.register(SchemaInitStep())
    registry.register(IngestKaikkiStep())
    registry.register(IngestTatoebaStep())
    registry.register(IngestOpusStep())
    registry.register(IngestWordNetStep())
    registry.register(EnrichIPAStep())
    registry.register(TransformLinkingStep())
    registry.register(TransformPhrasesStep())
    registry.register(TransformRelationsStep())
    registry.register(EnrichTranslationStep())
    registry.register(EnrichReflexStep())
    registry.register(EnrichScenariosStep())
    registry.register(EnrichAudioStep())
    registry.register(ExportSQLiteStep())
    registry.register(ExportCore3000Step())
    registry.register(ExportJsonStep())
    return registry


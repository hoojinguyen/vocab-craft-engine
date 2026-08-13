from typing import List, Dict, Optional
from src.pipeline.core.base_step import BaseStep

class StepRegistry:
    def __init__(self):
        self._steps: List[BaseStep] = []
        self._step_map: Dict[str, BaseStep] = {}

    def register(self, step: BaseStep) -> None:
        if step.name in self._step_map:
            raise ValueError(f"Step with name '{step.name}' is already registered.")
        self._steps.append(step)
        self._step_map[step.name] = step

    def get_all_steps(self) -> List[BaseStep]:
        return list(self._steps)

    def get_step(self, name: str) -> Optional[BaseStep]:
        return self._step_map.get(name)

    def filter_steps(
        self,
        include_steps: Optional[List[str]] = None,
        skip_steps: Optional[List[str]] = None
    ) -> List[BaseStep]:
        steps = list(self._steps)
        if include_steps:
            unknown = [s for s in include_steps if s not in self._step_map]
            if unknown:
                raise ValueError(f"Unknown step name(s): {', '.join(unknown)}")
            inc_set = set(include_steps)
            steps = [s for s in steps if s.name in inc_set]
        if skip_steps:
            unknown = [s for s in skip_steps if s not in self._step_map]
            if unknown:
                raise ValueError(f"Unknown step name(s): {', '.join(unknown)}")
            skip_set = set(skip_steps)
            steps = [s for s in steps if s.name not in skip_set]
        return steps


def get_default_registry() -> StepRegistry:
    from src.pipeline.steps import (
        SchemaInitStep,
        KaikkiIngestionStep,
        TatoebaIngestionStep,
        SentenceLinkingStep,
        NLPEnrichmentStep,
        ReflexDrillsStep,
        ScenarioTreesStep,
        IPAMappingStep,
        AudioGenerationStep,
        PhraseMWEStep,
        RelationsTopicsStep,
        VietnameseBackfillStep,
        CorePackStep,
        SentenceCoverageStep,
        SQLiteExportStep
    )

    registry = StepRegistry()
    registry.register(SchemaInitStep())
    registry.register(KaikkiIngestionStep())
    registry.register(TatoebaIngestionStep())
    registry.register(SentenceCoverageStep())
    registry.register(SentenceLinkingStep())
    registry.register(NLPEnrichmentStep())
    registry.register(ReflexDrillsStep())
    registry.register(ScenarioTreesStep())
    registry.register(IPAMappingStep())
    registry.register(AudioGenerationStep())
    registry.register(PhraseMWEStep())
    registry.register(RelationsTopicsStep())
    registry.register(VietnameseBackfillStep())
    registry.register(CorePackStep())
    registry.register(SQLiteExportStep())
    return registry


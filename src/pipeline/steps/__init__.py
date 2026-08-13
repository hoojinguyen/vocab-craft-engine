import importlib

SchemaInitStep = importlib.import_module("src.pipeline.steps.01_schema_init").SchemaInitStep
KaikkiIngestionStep = importlib.import_module("src.pipeline.steps.02_kaikki_ingestion").KaikkiIngestionStep
TatoebaIngestionStep = importlib.import_module("src.pipeline.steps.03_tatoeba_ingestion").TatoebaIngestionStep
SentenceLinkingStep = importlib.import_module("src.pipeline.steps.04_sentence_linking").SentenceLinkingStep
NLPEnrichmentStep = importlib.import_module("src.pipeline.steps.05_nlp_enrichment").NLPEnrichmentStep
ReflexDrillsStep = importlib.import_module("src.pipeline.steps.06_reflex_drills").ReflexDrillsStep
ScenarioTreesStep = importlib.import_module("src.pipeline.steps.07_scenario_trees").ScenarioTreesStep
IPAMappingStep = importlib.import_module("src.pipeline.steps.08_ipa_mapping").IPAMappingStep
AudioGenerationStep = importlib.import_module("src.pipeline.steps.09_audio_generation").AudioGenerationStep
PhraseMWEStep = importlib.import_module("src.pipeline.steps.10_phrase_mwe").PhraseMWEStep
RelationsTopicsStep = importlib.import_module("src.pipeline.steps.11_relations_topics").RelationsTopicsStep
VietnameseBackfillStep = importlib.import_module("src.pipeline.steps.12_vietnamese_backfill").VietnameseBackfillStep
CorePackStep = importlib.import_module("src.pipeline.steps.13_core_pack").CorePackStep
SentenceCoverageStep = importlib.import_module("src.pipeline.steps.14_sentence_coverage").SentenceCoverageStep
SQLiteExportStep = importlib.import_module("src.pipeline.steps.15_sqlite_export").SQLiteExportStep

__all__ = [
    "SchemaInitStep",
    "KaikkiIngestionStep",
    "TatoebaIngestionStep",
    "SentenceLinkingStep",
    "NLPEnrichmentStep",
    "ReflexDrillsStep",
    "ScenarioTreesStep",
    "IPAMappingStep",
    "AudioGenerationStep",
    "PhraseMWEStep",
    "RelationsTopicsStep",
    "VietnameseBackfillStep",
    "CorePackStep",
    "SentenceCoverageStep",
    "SQLiteExportStep",
]

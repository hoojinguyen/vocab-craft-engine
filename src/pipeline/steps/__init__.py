import importlib

SchemaInitStep = importlib.import_module("src.pipeline.steps.01_schema_init").SchemaInitStep
KaikkiIngestionStep = importlib.import_module("src.pipeline.steps.02_kaikki_ingestion").KaikkiIngestionStep
TatoebaIngestionStep = importlib.import_module("src.pipeline.steps.03_tatoeba_ingestion").TatoebaIngestionStep
SentenceLinkingStep = importlib.import_module("src.pipeline.steps.04_sentence_linking").SentenceLinkingStep

__all__ = [
    "SchemaInitStep",
    "KaikkiIngestionStep",
    "TatoebaIngestionStep",
    "SentenceLinkingStep",
]

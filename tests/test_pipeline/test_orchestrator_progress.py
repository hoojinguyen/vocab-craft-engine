from pathlib import Path
import pytest
from unittest.mock import MagicMock
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.registry import get_default_registry
from src.pipeline.monitor.progress import ProgressReporter, StepProgress
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.enrichment.translation import HybridTranslator
from src.pipeline.steps.ingest_kaikki import IngestKaikkiStep
from src.pipeline.steps.ingest_opus import IngestOpusStep
from src.pipeline.steps.enrich_translation import EnrichTranslationStep


def test_orchestrator_initializes_progress_reporter(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "orch_test.duckdb")
    db_mgr.init_schema()

    progress_events = []

    def on_prog(name, cur, tot, msg=""):
        progress_events.append((name, cur, tot))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    ctx = PipelineContext(db_manager=db_mgr, progress_reporter=reporter)

    registry = get_default_registry()
    orch = PipelineOrchestrator(registry=registry)
    orch._execute_single_step(
        registry.get_step("schema_init"), ctx, dry_run=True, force_all=False, force_steps=set(), retry_policy=None
    )
    db_mgr.close()


def test_orchestrator_run_initializes_reporter_and_dag_metadata(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "orch_run_test.duckdb")
    db_mgr.init_schema()

    ctx = PipelineContext(db_manager=db_mgr)
    args = MagicMock()
    args.dry_run = True
    args.tui = False
    args.no_tui = True
    args.force_all = False
    args.force_steps = set()
    args.max_retries = 1
    args.log_dir = str(tmp_path / "logs")
    ctx.args = args

    registry = get_default_registry()
    orch = PipelineOrchestrator(registry=registry)
    summary = orch.run(ctx)

    assert summary is not None
    assert ctx.progress_reporter is not None
    assert orch.dashboard is not None

    # Verify DAG levels and metadata map populated
    assert "schema_init" in orch.dashboard.step_metadata
    assert "ingest_kaikki" in orch.dashboard.step_metadata
    kaikki_meta = orch.dashboard.step_metadata["ingest_kaikki"]
    assert "Ingest Kaikki" in kaikki_meta["description"]
    assert "schema_init" in kaikki_meta["depends_on"]
    assert "words" in kaikki_meta["produces"]
    assert kaikki_meta["type"] in ("cpu", "io", "gpu")

    db_mgr.close()


def test_kaikki_ingestor_streams_progress(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "kaikki_prog.duckdb")
    db_mgr.init_schema()

    sample_kaikki = tmp_path / "kaikki_sample.jsonl"
    sample_kaikki.write_text(
        '{"word": "cat", "pos": "noun", "lang": "English", "senses": [{"glosses": ["feline animal"]}]}\n'
        '{"word": "dog", "pos": "noun", "lang": "English", "senses": [{"glosses": ["canine animal"]}]}\n',
        encoding="utf-8",
    )

    progress_events = []

    def on_prog(name, cur, tot, msg=""):
        progress_events.append((name, cur, tot, msg))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    step_prog = StepProgress(step_name="ingest_kaikki", total=2, reporter=reporter)

    ingestor = KaikkiIngestor()
    count = ingestor.ingest(db_mgr, sample_kaikki, progress=step_prog)

    assert count == 2
    assert len(progress_events) >= 1
    assert progress_events[-1][0] == "ingest_kaikki"
    assert progress_events[-1][1] == 2

    db_mgr.close()


def test_opus_ingestor_streams_progress(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "opus_prog.duckdb")
    db_mgr.init_schema()

    en_file = tmp_path / "test.en"
    vi_file = tmp_path / "test.vi"
    en_file.write_text("Hello world this is sentence one.\nSecond sample sentence goes here.\n", encoding="utf-8")
    vi_file.write_text("Xin chao the gioi cau mot.\nCau vi du thu hai o day.\n", encoding="utf-8")

    progress_events = []

    def on_prog(name, cur, tot, msg=""):
        progress_events.append((name, cur, tot, msg))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    step_prog = StepProgress(step_name="ingest_opus", total=2, reporter=reporter)

    ingestor = OpusIngestor()
    count = ingestor.ingest_pair(db_mgr, en_file, vi_file, source="opus", progress=step_prog)

    assert count == 2
    assert len(progress_events) >= 1
    assert progress_events[-1][0] == "ingest_opus"
    assert progress_events[-1][1] == 2

    db_mgr.close()


def test_hybrid_translator_streams_progress(tmp_path):
    db_mgr = DuckDBManager(tmp_path / "trans_prog.duckdb")
    db_mgr.init_schema()

    db_mgr.insert_batch_fast(
        "words",
        [
            {"lemma": "run", "pos": "verb", "source": "kaikki"},
            {"lemma": "jump", "pos": "verb", "source": "kaikki"},
        ],
    )
    db_mgr.insert_batch_fast(
        "definitions",
        [
            {"word_id": 1, "definition_en": "to move fast", "source": "kaikki"},
            {"word_id": 2, "definition_en": "to leap into the air", "source": "kaikki"},
        ],
    )
    db_mgr.insert_batch_fast(
        "phrases",
        [
            {"phrase": "run away", "phrase_type": "phrasal_verb", "definition_en": "to escape"},
            {"phrase": "jump up", "phrase_type": "phrasal_verb", "definition_en": "to leap upward"},
        ],
    )

    progress_events = []

    def on_prog(name, cur, tot, msg=""):
        progress_events.append((name, cur, tot, msg))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    step_prog = StepProgress(step_name="enrich_translation", total=4, reporter=reporter)

    translator = HybridTranslator(db_mgr)
    count_defs = translator.translate_definitions(batch_size=1, progress=step_prog)
    count_phrases = translator.translate_phrases(batch_size=1, progress=step_prog)

    assert count_defs == 2
    assert count_phrases == 2
    assert len(progress_events) >= 2

    db_mgr.close()


def test_pipeline_steps_integrate_progress(tmp_path, monkeypatch):
    db_mgr = DuckDBManager(tmp_path / "steps_prog.duckdb")
    db_mgr.init_schema()

    progress_events = []

    def on_prog(name, cur, tot, msg=""):
        progress_events.append((name, cur, tot, msg))

    reporter = ProgressReporter(callback=on_prog, throttle_interval=0.0)
    ctx = PipelineContext(db_manager=db_mgr, progress_reporter=reporter)

    # Test Kaikki step with sample data
    sample_kaikki = tmp_path / "kaikki_sample.jsonl"
    sample_kaikki.write_text('{"word": "test", "pos": "noun", "lang": "English", "senses": [{"glosses": ["a test"]}]}\n')
    monkeypatch.setattr("src.pipeline.steps.ingest_kaikki.KAIKKI_JSON_PATH", sample_kaikki)
    step_k = IngestKaikkiStep()
    res_k = step_k.run(ctx)
    assert res_k.items_processed == 1
    assert any(e[0] == "ingest_kaikki" for e in progress_events)

    # Test Opus step with sample data
    en_file = tmp_path / "test.en"
    vi_file = tmp_path / "test.vi"
    en_file.write_text("A simple English sentence here.\n")
    vi_file.write_text("Mot cau tieng Anh don gian o day.\n")
    monkeypatch.setattr("src.pipeline.steps.ingest_opus.OPENSUBTITLES_EN", en_file)
    monkeypatch.setattr("src.pipeline.steps.ingest_opus.OPENSUBTITLES_VI", vi_file)
    step_o = IngestOpusStep()
    res_o = step_o.run(ctx)
    assert res_o.items_processed == 1
    assert any(e[0] == "ingest_opus" for e in progress_events)

    # Test Translation step
    step_t = EnrichTranslationStep()
    res_t = step_t.run(ctx)
    assert res_t.items_processed >= 1
    assert any(e[0] == "enrich_translation" for e in progress_events)

    db_mgr.close()

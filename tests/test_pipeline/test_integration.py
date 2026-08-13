import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.orchestrator import PipelineOrchestrator
from src.pipeline.core.result import StepResult, StepStatus


class StepA(BaseStep):
    name = "step_a"
    description = "Ingest words"
    depends_on = []
    produces = ["words"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        ctx.db.insert_batch("words", [
            {"lemma": "run", "pos": "verb", "source": "kaikki"},
            {"lemma": "walk", "pos": "verb", "source": "kaikki"},
        ])
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=2)


class StepB(BaseStep):
    name = "step_b"
    description = "Enrich definitions"
    depends_on = ["step_a"]
    produces = ["definitions"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        words_count = ctx.db.count_rows("words")
        ctx.db.insert_batch("definitions", [
            {"word_id": 1, "definition_en": "to move fast", "source": "kaikki"},
            {"word_id": 2, "definition_en": "to move on foot", "source": "kaikki"},
        ])
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=words_count)


class StepC(BaseStep):
    name = "step_c"
    description = "Extract phrases"
    depends_on = ["step_b"]
    produces = ["phrases"]

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        ctx.db.insert_batch("phrases", [
            {"phrase": "run out", "phrase_type": "phrasal_verb", "definition_en": "use up"},
        ])
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=1)


class DummyArgs:
    dry_run = False
    force_all = False
    force_step = None
    max_retries = 0
    tui = False
    log_dir = "logs"


@pytest.fixture
def integration_env(tmp_path):
    db_path = tmp_path / "staging_integration.duckdb"
    db_mgr = DuckDBManager(db_path=db_path)
    db_mgr.init_schema()
    context = PipelineContext(db_manager=db_mgr, args=DummyArgs())
    yield context, tmp_path
    db_mgr.close()


def test_full_pipeline_dag_execution_and_caching(integration_env):
    ctx, tmp_path = integration_env

    # 1. Initial Run
    src_file_a = tmp_path / "source_a.txt"
    src_file_a.write_text("raw words v1")

    step_a = StepA()
    step_a.source_files = [src_file_a]
    step_b = StepB()
    step_c = StepC()

    orchestrator = PipelineOrchestrator(steps=[step_a, step_b, step_c])
    summary1 = orchestrator.run(ctx)

    assert summary1.has_failures is False
    assert len(summary1.results) == 3
    assert all(r.status == StepStatus.SUCCESS for r in summary1.results)
    assert ctx.db.count_rows("words") == 2
    assert ctx.db.count_rows("definitions") == 2
    assert ctx.db.count_rows("phrases") == 1

    # 2. Second Run (No changes) -> All steps should be SKIPPED via caching
    orchestrator2 = PipelineOrchestrator(steps=[StepA(), StepB(), StepC()])
    orchestrator2.steps[0].source_files = [src_file_a]
    summary2 = orchestrator2.run(ctx)

    assert summary2.has_failures is False
    assert all(r.status == StepStatus.SKIPPED for r in summary2.results)

    # 3. Modify source file of StepA -> StepA invalidates, cascading to B and C
    src_file_a.write_text("raw words v2 updated content")
    orchestrator3 = PipelineOrchestrator(steps=[StepA(), StepB(), StepC()])
    orchestrator3.steps[0].source_files = [src_file_a]
    summary3 = orchestrator3.run(ctx)

    assert summary3.has_failures is False
    assert summary3.results[0].status == StepStatus.SUCCESS
    assert summary3.results[1].status == StepStatus.SUCCESS
    assert summary3.results[2].status == StepStatus.SUCCESS

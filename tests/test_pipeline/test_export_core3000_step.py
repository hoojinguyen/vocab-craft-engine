from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepStatus
from src.pipeline.steps.export_core3000 import ExportCore3000Step


def test_export_core3000_step_execution():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        out_dir = Path(tmp_dir) / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        db_mgr.insert_batch_fast("words", [
            {"id": 1, "lemma": "hello", "pos": "noun", "frequency_rank": 10, "source": "kaikki"}
        ])

        ctx = PipelineContext(db_manager=db_mgr)
        step = ExportCore3000Step()

        # Patch output path for test
        import config.settings
        orig_out = config.settings.OUTPUT_DIR
        config.settings.OUTPUT_DIR = out_dir

        try:
            res = step.run(ctx)
            assert res.status == StepStatus.SUCCESS
            assert res.items_processed == 1
            assert (out_dir / "core_3000.db").exists()
            assert (out_dir / "quality_report.md").exists()
        finally:
            config.settings.OUTPUT_DIR = orig_out

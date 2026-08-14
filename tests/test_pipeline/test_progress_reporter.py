import time
import pytest
from src.pipeline.monitor.progress import ProgressReporter, StepProgress
from src.pipeline.core.context import PipelineContext
from src.db.duckdb_manager import DuckDBManager


def test_progress_reporter_emission():
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.0)
    step_prog = StepProgress(step_name="test_step", total=100, reporter=reporter)

    step_prog.advance(25, "Processing batch 1")
    step_prog.advance(25, "Processing batch 2")

    assert len(events) == 2
    assert events[0] == ("test_step", 25, 100, "Processing batch 1")
    assert events[1] == ("test_step", 50, 100, "Processing batch 2")


def test_progress_reporter_context_manager(tmp_path):
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.0)
    db_mgr = DuckDBManager(tmp_path / "test.duckdb")
    ctx = PipelineContext(db_manager=db_mgr, progress_reporter=reporter)

    prog = ctx.create_progress("ingest_test", total=1000)
    with prog.track_batch(200):
        pass

    assert prog.current == 200
    assert len(events) == 1
    assert events[0] == ("ingest_test", 200, 1000, "")
    db_mgr.close()


def test_progress_reporter_throttling():
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    # Throttle with 0.1s interval
    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.1)
    step_prog = StepProgress(step_name="throttle_test", total=100, reporter=reporter)

    # 1. Advance to 10 (not 0, not 100) -> first time emitted because last_time = 0.0
    step_prog.advance(10, "10%")
    assert len(events) == 1
    assert events[-1] == ("throttle_test", 10, 100, "10%")

    # 2. Immediately advance to 20 -> should be throttled (not emitted)
    step_prog.advance(10, "20%")
    assert len(events) == 1

    # 3. Advance to 100 (completion) -> should always emit even if throttled
    step_prog.advance(80, "100%")
    assert len(events) == 2
    assert events[-1] == ("throttle_test", 100, 100, "100%")


def test_progress_reporter_none_safe():
    # No callback
    reporter = ProgressReporter(callback=None)
    step_prog = StepProgress(step_name="none_test", total=50, reporter=reporter)
    step_prog.advance(10)
    assert step_prog.current == 10

    # No reporter
    step_prog_no_rep = StepProgress(step_name="no_rep", total=50, reporter=None)
    step_prog_no_rep.advance(5)
    assert step_prog_no_rep.current == 5


def test_track_batch_exception_handling():
    events = []

    def on_progress(step_name: str, current: int, total: int, message: str):
        events.append((step_name, current, total, message))

    reporter = ProgressReporter(callback=on_progress, throttle_interval=0.0)
    step_prog = StepProgress(step_name="err_test", total=100, reporter=reporter)

    with pytest.raises(ValueError):
        with step_prog.track_batch(50, "failed batch"):
            raise ValueError("boom")

    # Should not have advanced on exception
    assert step_prog.current == 0
    assert len(events) == 0

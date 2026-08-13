import json
from pathlib import Path
import pytest
from src.pipeline.monitor.metrics import DataQualityMetrics
from src.pipeline.monitor.run_logger import RunLogger
from src.pipeline.core.result import StepResult, StepStatus, PipelineSummary


def test_data_quality_metrics_calculation():
    # Test default initialization
    dq_empty = DataQualityMetrics()
    assert dq_empty.total_records == 0
    assert dq_empty.valid_records == 0
    assert dq_empty.invalid_records == 0
    assert dq_empty.schema_compliance_ratio == 1.0

    # Test calculations and to_dict
    dq = DataQualityMetrics(
        total_records=100,
        valid_records=95,
        invalid_records=5,
        additional_stats={"duplicates": 2}
    )
    assert dq.schema_compliance_ratio == 0.95
    dict_repr = dq.to_dict()
    assert dict_repr == {
        "total_records": 100,
        "valid_records": 95,
        "invalid_records": 5,
        "schema_compliance_ratio": 0.95,
        "duplicates": 2
    }


def test_run_logger_creates_json_artifact(tmp_path):
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir=log_dir, run_id="run_test_123")

    # Check log file created
    assert logger.log_file_path.exists()
    assert logger.log_file_path.name.startswith("pipeline_")
    assert logger.log_file_path.name.endswith(".log")

    dq_metrics = DataQualityMetrics(total_records=50, valid_records=48, invalid_records=2).to_dict()

    results = [
        StepResult(
            step_name="test_step_1",
            status=StepStatus.SUCCESS,
            execution_time_seconds=1.2,
            items_processed=50,
            retry_count=0,
            data_metrics=dq_metrics
        )
    ]
    summary = PipelineSummary(total_time_seconds=1.2, results=results, has_failures=False)

    json_path = logger.save_run_summary(summary)
    assert json_path.exists()
    assert json_path == log_dir / "runs" / "run_test_123.json"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["run_id"] == "run_test_123"
    assert data["status"] == "SUCCESS"
    assert data["is_resumed_run"] is False
    assert data["total_runtime_seconds"] == 1.2
    assert "system_info" in data
    assert "python_version" in data["system_info"]
    assert "platform" in data["system_info"]
    assert data["summary_metrics"]["total_steps"] == 1
    assert data["summary_metrics"]["successful_steps"] == 1
    assert data["summary_metrics"]["failed_steps"] == 0
    assert data["summary_metrics"]["skipped_steps"] == 0
    assert data["summary_metrics"]["total_items_processed"] == 50
    assert data["summary_metrics"]["overall_throughput_items_per_sec"] == 41.67
    assert len(data["steps"]) == 1
    assert data["steps"][0]["step_name"] == "test_step_1"
    assert data["steps"][0]["status"] == "SUCCESS"
    assert data["steps"][0]["data_metrics"]["valid_records"] == 48

    latest_link = log_dir / "latest_run.json"
    assert latest_link.exists()
    with open(latest_link, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    assert latest_data["run_id"] == "run_test_123"


def test_run_logger_handles_failed_run_and_tracebacks(tmp_path):
    log_dir = tmp_path / "logs"
    logger = RunLogger(log_dir=log_dir, run_id="run_failed_456")

    err = RuntimeError("Simulated failure")
    tb = "Traceback (most recent call last):\n  File ...\nRuntimeError: Simulated failure"

    results = [
        StepResult(
            step_name="failing_step",
            status=StepStatus.FAILED,
            execution_time_seconds=0.5,
            items_processed=0,
            retry_count=3,
            message="Simulated failure",
            error=err,
            error_traceback=tb
        )
    ]
    summary = PipelineSummary(total_time_seconds=0.5, results=results, has_failures=True)

    json_path = logger.save_run_summary(summary, is_resumed=True)
    assert json_path.exists()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["run_id"] == "run_failed_456"
    assert data["status"] == "FAILED"
    assert data["is_resumed_run"] is True
    assert data["summary_metrics"]["failed_steps"] == 1
    assert data["steps"][0]["error_details"]["error_message"] == "Simulated failure"
    assert data["steps"][0]["error_details"]["stacktrace"] == tb


def test_dashboard_initialization_no_tui():
    from src.pipeline.monitor.dashboard import RichPipelineDashboard
    dash = RichPipelineDashboard(enabled=False)
    dash.start()
    assert dash.is_active is False
    dash.set_steps(["step_1", "step_2"])
    dash.update_step("step_1", "RUNNING", duration=1.0, items=10, retries=1, metrics_str="50%")
    dash.add_log("Testing log line")
    dash.stop()
    assert dash.is_active is False


def test_dashboard_set_steps_and_updates():
    from src.pipeline.monitor.dashboard import RichPipelineDashboard
    dash = RichPipelineDashboard(enabled=False)
    dash.set_steps(["step_a", "step_b"])
    assert "step_a" in dash.steps_data
    assert "step_b" in dash.steps_data
    assert dash.steps_data["step_a"]["status"] == "PENDING"

    dash.update_step("step_a", "SUCCESS", duration=2.5, items=100, retries=0, metrics_str="100%")
    assert dash.steps_data["step_a"]["status"] == "SUCCESS"
    assert dash.steps_data["step_a"]["duration"] == 2.5
    assert dash.steps_data["step_a"]["items"] == 100
    assert dash.steps_data["step_a"]["retries"] == 0
    assert dash.steps_data["step_a"]["metrics"] == "100%"

    # Add 12 logs and check buffer capping at 10
    for i in range(12):
        dash.add_log(f"Log line {i}")
    assert len(dash.logs_buffer) == 10
    assert dash.logs_buffer[0] == "Log line 2"
    assert dash.logs_buffer[-1] == "Log line 11"


def test_dashboard_layout_generation():
    from src.pipeline.monitor.dashboard import RichPipelineDashboard
    dash = RichPipelineDashboard(enabled=False)
    dash.set_steps(["step_1"])
    dash.update_step("step_1", "RUNNING", duration=1.2, items=5, retries=0, metrics_str="OK")
    dash.add_log("Log 1")

    layout = dash._generate_layout()
    assert layout is not None
    assert layout["header"] is not None
    assert layout["body"] is not None
    assert layout["footer"] is not None


def test_dashboard_start_and_stop_with_tty(monkeypatch):
    from rich.console import Console
    from src.pipeline.monitor.dashboard import RichPipelineDashboard

    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))

    dash = RichPipelineDashboard(enabled=True)
    assert dash.enabled is True

    dash.set_steps(["step_1"])
    dash.start()
    assert dash.is_active is True
    assert dash.live is not None

    dash.update_step("step_1", "SUCCESS")
    dash.add_log("Log message")
    dash.stop()
    assert dash.is_active is False


def test_dashboard_logging_redirection(monkeypatch):
    import logging
    from rich.console import Console
    from src.pipeline.monitor.dashboard import RichPipelineDashboard

    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))

    root_logger = logging.getLogger()
    orig_level = root_logger.level
    root_logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    root_logger.addHandler(stream_handler)

    dash = RichPipelineDashboard(enabled=True)
    dash.set_steps(["step_1"])
    dash.start()

    # Verify stream_handler was removed, and DashboardLoggingHandler was added
    assert stream_handler not in root_logger.handlers
    assert dash.dashboard_handler in root_logger.handlers

    # Log a message and verify it was added to dashboard's buffer
    logging.getLogger("test_logger").info("Hello dashboard log redirection!")
    assert any("Hello dashboard log redirection!" in log for log in dash.logs_buffer)

    # Stop dashboard and verify original state is restored
    dash.stop()
    assert stream_handler in root_logger.handlers
    assert dash.dashboard_handler not in root_logger.handlers

    # Cleanup the test-added stream_handler and restore level
    root_logger.removeHandler(stream_handler)
    root_logger.setLevel(orig_level)





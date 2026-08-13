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

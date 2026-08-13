import pytest
from scripts.benchmark_pipeline import run_benchmark


def test_benchmark_script_runs():
    report = run_benchmark(dry_run=True)
    assert "total_time_seconds" in report
    assert "memory_peak_mb" in report
    assert isinstance(report["total_time_seconds"], float)

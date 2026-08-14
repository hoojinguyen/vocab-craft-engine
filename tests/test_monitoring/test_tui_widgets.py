import pytest
from src.monitoring.tui.widgets import (
    HeaderWidget,
    StepListWidget,
    MetricsCard,
    LogStreamWidget,
)


def test_header_widget_init_and_update():
    header = HeaderWidget(title="VOCAB CRAFT TEST")
    assert "VOCAB CRAFT TEST" in header.title
    header.update_status(status="RUNNING", elapsed=65.0, workers=4)
    assert header.status == "RUNNING"
    assert header.elapsed_str == "00:01:05"


def test_step_list_widget_init_and_update():
    step_list = StepListWidget()
    step_list.init_steps(["ingest_kaikki", "translate_defs"])
    assert "ingest_kaikki" in step_list.steps_data
    assert step_list.steps_data["ingest_kaikki"]["status"] == "PENDING"

    step_list.update_step("ingest_kaikki", status="SUCCESS", duration=12.5, items=5000, retries=0, metrics="400 items/s")
    assert step_list.steps_data["ingest_kaikki"]["status"] == "SUCCESS"
    assert step_list.steps_data["ingest_kaikki"]["items"] == 5000


def test_metrics_card_update():
    card = MetricsCard()
    card.update_metrics(cpu_pct=35.5, memory_mb=512.0, db_size_mb=120.5, throughput=1500.0, eta_sec=90.0)
    assert card.cpu_pct == 35.5
    assert card.memory_mb == 512.0
    assert card.eta_str == "00:01:30"


def test_log_stream_widget_instantiation():
    log_stream = LogStreamWidget()
    assert log_stream is not None

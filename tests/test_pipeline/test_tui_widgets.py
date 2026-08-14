import pytest
from src.pipeline.monitor.widgets.dag_panel import DAGPanel
from src.pipeline.monitor.widgets.header import HeaderWidget
from src.pipeline.monitor.widgets.log_stream import LogStreamWidget
from src.pipeline.monitor.widgets.step_detail import StepDetailWidget
from src.pipeline.monitor.widgets.step_table import StepTable, make_progress_bar
from src.pipeline.monitor.widgets.telemetry import TelemetryPanel


def test_make_progress_bar():
    bar_0 = make_progress_bar(0, 100, width=10)
    assert "0%" in bar_0
    bar_50 = make_progress_bar(50, 100, width=10)
    assert "50%" in bar_50
    bar_100 = make_progress_bar(100, 100, width=10)
    assert "100%" in bar_100
    bar_invalid = make_progress_bar(0, 0, width=10)
    assert "--" in bar_invalid


def test_dag_panel_structure():
    panel = DAGPanel()
    mock_levels = [["schema_init"], ["ingest_kaikki", "ingest_tatoeba"]]
    panel.init_dag(mock_levels)
    assert "schema_init" in panel.nodes
    assert "ingest_kaikki" in panel.nodes
    assert panel.nodes["schema_init"] == "PENDING"

    panel.update_node_status("schema_init", "RUNNING")
    assert panel.nodes["schema_init"] == "RUNNING"

    panel.update_node_status("schema_init", "SUCCESS")
    assert panel.nodes["schema_init"] == "SUCCESS"


def test_step_detail_display():
    detail = StepDetailWidget()
    sample_data = {
        "name": "ingest_kaikki",
        "status": "RUNNING",
        "description": "Ingest Kaikki Wiktionary",
        "type": "cpu",
        "depends_on": "schema_init",
        "produces": "words, definitions",
        "items": 12500,
        "duration": 4.5,
        "retries": 0,
        "error": "",
    }
    rendered = detail.format_step_detail(sample_data)
    assert "ingest_kaikki" in rendered
    assert "words, definitions" in rendered

    empty_rendered = detail.format_step_detail(None)
    assert "Select a step" in empty_rendered

    err_data = {
        "name": "export_failed",
        "status": "FAILED",
        "description": "Export step",
        "type": "io",
        "depends_on": "ingest_kaikki",
        "produces": "output.json",
        "items": 0,
        "duration": 1.2,
        "retries": 1,
        "error": "Disk full",
    }
    err_rendered = detail.format_step_detail(err_data)
    assert "Disk full" in err_rendered


def test_header_widget():
    header = HeaderWidget(title="TEST PIPELINE")
    assert header.title_str == "TEST PIPELINE"
    assert header.status == "IDLE"
    header.update_status("RUNNING", elapsed=125.0, workers=8, level="2/5")
    assert header.status == "RUNNING"
    assert header.elapsed_seconds == 125.0
    assert header.worker_count == 8
    assert header.current_level == "2/5"


def test_step_table_data():
    table = StepTable()
    steps = ["step_a", "step_b"]
    table.init_steps(steps)
    assert "step_a" in table.steps_data
    assert "step_b" in table.steps_data
    assert table.steps_data["step_a"]["status"] == "PENDING"

    table.update_step_progress("step_a", 50, 100)
    assert table.steps_data["step_a"]["current"] == 50
    assert table.steps_data["step_a"]["total"] == 100

    table.update_step_status("step_a", "SUCCESS", duration=2.5, items=100)
    assert table.steps_data["step_a"]["status"] == "SUCCESS"
    assert table.steps_data["step_a"]["duration"] == 2.5
    assert table.steps_data["step_a"]["items"] == 100


def test_telemetry_panel():
    telemetry = TelemetryPanel()
    # Test update without errors
    telemetry.update_telemetry(
        cpu_pct=25.5,
        ram_mb=512.0,
        db_size_mb=128.5,
        throughput=45000.0,
        cache_hits=80,
        argos_count=15,
        google_count=5,
    )


def test_log_stream_widget():
    log_widget = LogStreamWidget()
    assert log_widget is not None

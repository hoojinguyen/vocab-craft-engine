import logging
import pytest
from src.pipeline.monitor.dashboard import DashboardLoggingHandler, TextualPipelineDashboard


def test_dashboard_initialization():
    app = TextualPipelineDashboard(enabled=False)
    app.set_dag_levels(
        [["schema_init"], ["ingest_kaikki"]],
        step_info_map={
            "schema_init": {
                "description": "Initialize DuckDB schemas",
                "type": "duckdb",
                "depends_on": [],
                "produces": ["tables"],
            }
        },
    )
    assert "schema_init" in app.step_metadata
    assert "ingest_kaikki" in app.step_metadata
    assert app.step_metadata["schema_init"]["description"] == "Initialize DuckDB schemas"
    assert app.step_metadata["schema_init"]["type"] == "duckdb"
    assert app.selected_step_name == "schema_init"


def test_dashboard_step_updates():
    app = TextualPipelineDashboard(enabled=False)
    app.set_dag_levels([["schema_init"]])
    app.update_step("schema_init", "RUNNING")
    assert app.step_metadata["schema_init"]["status"] == "RUNNING"

    app.update_step(
        "schema_init",
        "FAILED",
        duration=1.5,
        items=50,
        retries=2,
        error_or_metrics="Connection error",
    )
    assert app.step_metadata["schema_init"]["status"] == "FAILED"
    assert app.step_metadata["schema_init"]["duration"] == 1.5
    assert app.step_metadata["schema_init"]["items"] == 50
    assert app.step_metadata["schema_init"]["retries"] == 2
    assert app.step_metadata["schema_init"]["error"] == "Connection error"


def test_dashboard_compatibility_helper():
    app = TextualPipelineDashboard(enabled=False)
    app.set_steps(["step1", "step2"])
    assert "step1" in app.step_metadata
    assert "step2" in app.step_metadata


def test_dashboard_logging_handler():
    app = TextualPipelineDashboard(enabled=False)
    logs_received = []
    # Mock add_log to capture formatted logs
    app.add_log = lambda msg: logs_received.append(msg)

    handler = DashboardLoggingHandler(app)

    # Test start step
    rec_start = logging.LogRecord("test", logging.INFO, "test.py", 10, "=== START: ingest_kaikki", (), None)
    handler.emit(rec_start)
    assert any("START STEP" in m and "ingest_kaikki" in m for m in logs_received)

    # Test end step
    rec_end = logging.LogRecord("test", logging.INFO, "test.py", 11, "=== END: ingest_kaikki", (), None)
    handler.emit(rec_end)
    assert any("FINISHED STEP" in m and "ingest_kaikki" in m for m in logs_received)

    # Test error
    rec_err = logging.LogRecord("test", logging.ERROR, "test.py", 12, "Something went wrong", (), None)
    handler.emit(rec_err)
    assert any("ERROR" in m and "Something went wrong" in m for m in logs_received)

    # Test warning
    rec_warn = logging.LogRecord("test", logging.WARNING, "test.py", 13, "Low memory warning", (), None)
    handler.emit(rec_warn)
    assert any("WARNING" in m and "Low memory warning" in m for m in logs_received)

    # Test info
    rec_info = logging.LogRecord("test", logging.INFO, "test.py", 14, "Processed 100 rows", (), None)
    handler.emit(rec_info)
    assert any("Processed 100 rows" in m for m in logs_received)


def test_dashboard_actions_and_telemetry():
    app = TextualPipelineDashboard(enabled=False)
    app.set_dag_levels([["step_a"]])
    assert not app.is_paused
    app.action_toggle_pause()
    assert app.is_paused
    app.action_toggle_pause()
    assert not app.is_paused

    worker_executed = []
    app.set_worker(lambda: worker_executed.append(True))
    assert app._worker_func is not None

    # Test telemetry refresh
    app._periodic_telemetry_refresh()
    assert app.header_widget.status == "RUNNING"


@pytest.mark.asyncio
async def test_dashboard_async_pilot():
    app = TextualPipelineDashboard(enabled=True)
    app.set_dag_levels(
        [["schema_init"], ["ingest_kaikki"]],
        step_info_map={
            "schema_init": {
                "description": "Initialize DuckDB schemas",
                "type": "duckdb",
                "depends_on": [],
                "produces": ["tables"],
            },
            "ingest_kaikki": {
                "description": "Ingest Kaikki Wiktionary",
                "type": "cpu",
                "depends_on": ["schema_init"],
                "produces": ["words"],
            },
        },
    )

    async with app.run_test() as pilot:
        # Step detail initially shows first step
        assert app.selected_step_name == "schema_init"
        assert "schema_init" in str(app.step_detail.render())

        # Update step
        app.update_step("schema_init", "SUCCESS", duration=1.2, items=100)
        await pilot.pause()
        assert app.step_metadata["schema_init"]["status"] == "SUCCESS"

        # Update progress
        app.update_step_progress("ingest_kaikki", 50, 100, "Extracting")
        await pilot.pause()
        assert app.step_metadata["ingest_kaikki"]["items"] == 50

        # Simulate row selection/highlighting
        from textual.widgets import DataTable
        app.on_data_table_row_selected(DataTable.RowSelected(DataTable(), None, "ingest_kaikki"))
        assert app.selected_step_name == "ingest_kaikki"
        assert "ingest_kaikki" in str(app.step_detail.render())

        # Add log message
        app.add_log("[cyan]Testing log message[/cyan]")
        await pilot.pause()
        assert len(app.logs_buffer) > 0


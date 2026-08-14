import logging
import pytest
from src.monitoring.tui.progress import PipelineProgressApp, TUILoggingHandler
from src.pipeline.monitor.dashboard import TextualPipelineDashboard, DashboardLoggingHandler


def test_progress_app_init_and_steps():
    app = PipelineProgressApp(title="TEST MONITOR")
    app.set_steps(["step1", "step2"])
    assert "step1" in app.step_list.steps_data
    assert "step2" in app.step_list.steps_data


def test_tui_logging_handler():
    app = PipelineProgressApp()
    handler = TUILoggingHandler(app)
    logger = logging.getLogger("test_tui_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Test log record output")
    assert len(app.logs_buffer) > 0
    assert "Test log record output" in app.logs_buffer[-1]


def test_backward_compatibility_alias():
    # Verify TextualPipelineDashboard and DashboardLoggingHandler are compatible
    dashboard = TextualPipelineDashboard(title="LEGACY MONITOR")
    assert hasattr(dashboard, "steps_data")
    handler = DashboardLoggingHandler(dashboard)
    assert isinstance(handler, logging.Handler)


def test_progress_app_pause_and_refresh_actions():
    app = PipelineProgressApp()
    assert not app.is_paused
    app.action_toggle_pause()
    assert app.is_paused
    app.action_toggle_pause()
    assert not app.is_paused


def test_progress_app_step_status_update():
    app = PipelineProgressApp()
    app.set_steps(["ingest"])
    app.update_step_status("ingest", "SUCCESS", duration=1.5, items=200, retries=0, metrics="200 items/s")
    assert app.step_list.steps_data["ingest"]["status"] == "SUCCESS"
    assert app.step_list.steps_data["ingest"]["duration"] == 1.5
    assert app.step_list.steps_data["ingest"]["items"] == 200


def test_progress_app_headless_table_and_telemetry_updates():
    class HeadlessApp(PipelineProgressApp):
        async def on_mount(self):
            self.set_steps(["schema_init", "ingest_kaikki"])
            self.update_step("schema_init", "SUCCESS", duration=1.2, items=100)
            self.update_step("ingest_kaikki", "RUNNING")
            self._periodic_refresh()

            row_1 = self.step_list._table.get_row("schema_init")
            assert row_1[1] == "schema_init"
            assert "SUCCESS" in str(row_1[2])
            assert "1.2s" in str(row_1[3])

            row_2 = self.step_list._table.get_row("ingest_kaikki")
            assert row_2[1] == "ingest_kaikki"
            assert "RUNNING" in str(row_2[2])

            assert "Telemetry:" in str(self.metrics_card.render())
            self.exit()

    app = HeadlessApp()
    app.run(headless=True)

# Textual TUI Dashboard Migration Design

## 1. Overview
The goal is to migrate the pipeline monitoring terminal UI from `rich` to `textual`. This will provide a more professional, interactive interface with native support for scrolling, while maintaining the beautiful styling from the `rich` ecosystem.

## 2. Architecture & Approach
We will adopt the **Background Worker Thread (Approach 1)**:
- **Main Thread**: Owned by the `textual` application (`TextualPipelineDashboard.run()`).
- **Background Thread**: The `PipelineOrchestrator` will execute the pipeline steps in a background thread managed by Textual's `@work(thread=True)`.

### 2.1 File Changes
- **`src/pipeline/monitor/dashboard.py`**:
  - Replace `RichPipelineDashboard` with `TextualPipelineDashboard` inheriting from `textual.app.App`.
  - Use `textual.widgets.Header`, `textual.widgets.DataTable` (for steps overview), and `textual.widgets.RichLog` (for live logs).
  - Implement thread-safe UI updates using `call_from_thread()`.
- **`src/pipeline/core/orchestrator.py`**:
  - Modify `PipelineOrchestrator.run` to handle the Textual app lifecycle. 
  - When TUI is enabled, the orchestrator will start the Textual app, which in turn will trigger the pipeline execution loop via a background worker.
- **`tests/test_monitor.py`**:
  - Update unit tests to account for the new Textual dashboard (handling async/App lifecycle in tests).

## 3. Data Flow
1. User runs `make run`.
2. `PipelineOrchestrator.run()` is called.
3. If `--no-tui` is absent, the orchestrator instantiates `TextualPipelineDashboard`.
4. The dashboard is started (`app.run()`).
5. On the dashboard's `on_mount` event, it dispatches a background worker (`@work(thread=True)`) containing the pipeline's core execution loop.
6. The background worker iterates through the pipeline steps.
7. Logs are intercepted by `DashboardLoggingHandler`, which pushes them to the `RichLog` widget via `call_from_thread`.
8. Step updates (status, duration) are pushed to the `DataTable` widget via `call_from_thread`.
9. When the pipeline finishes, the dashboard displays a summary or auto-closes based on user preference.

## 4. Error Handling
- Exceptions occurring in the background worker must be caught and routed to the UI so the user knows the pipeline failed.
- The `DashboardLoggingHandler` will safely handle thread-crossing when emitting log records.

## 5. Testing Strategy
- Textual provides a testing framework (`async with app.run_test() as pilot`). We will rewrite `test_dashboard_logging_redirection` to use Textual's pilot testing, ensuring logs and step updates are correctly captured in the widgets.

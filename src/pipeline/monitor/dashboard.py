"""
Pipeline Dashboard re-exporting modular TUI progress app for backward compatibility.
"""

from src.monitoring.tui.progress import (
    PipelineProgressApp as TextualPipelineDashboard,
    TUILoggingHandler as DashboardLoggingHandler,
)

__all__ = [
    "TextualPipelineDashboard",
    "DashboardLoggingHandler",
]

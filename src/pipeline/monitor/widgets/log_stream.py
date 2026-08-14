from textual.widgets import RichLog


class LogStreamWidget(RichLog):
    """Auto-scrolling live logs viewer with Rich markup support."""

    DEFAULT_CSS = """
    LogStreamWidget {
        height: 1fr;
        background: #11111b;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, **kwargs)

    def write_log(self, message: str) -> None:
        self.write(message)

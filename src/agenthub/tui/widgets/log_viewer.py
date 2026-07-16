from __future__ import annotations

from typing import Optional

from textual.widgets import RichLog


class LogViewer(RichLog):
    DEFAULT_CSS = """
    LogViewer {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, *args: object, id: Optional[str] = None, **kwargs: object) -> None:
        super().__init__(highlight=True, markup=True, id=id or "log-viewer", *args, **kwargs)

    def write_line(self, text: str, severity: str = "info") -> None:
        color_map = {
            "info": "white",
            "tool": "yellow",
            "result": "green",
            "error": "red",
            "success": "green",
            "warning": "yellow",
        }
        color = color_map.get(severity, "white")
        self.write(f"[{color}]{text}[/{color}]")

    def clear_log(self) -> None:
        self.clear()
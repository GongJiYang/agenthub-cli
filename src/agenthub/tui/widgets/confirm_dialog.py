from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("enter", "confirm", "确认", show=False),
        Binding("escape", "cancel", "取消", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > Vertical {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDialog .dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    ConfirmDialog .dialog-message {
        text-align: center;
        margin-bottom: 1;
    }

    ConfirmDialog .dialog-buttons {
        align: center middle;
        height: 3;
        margin-top: 1;
    }

    ConfirmDialog Button {
        margin: 0 2;
    }
    """

    def __init__(
        self,
        title: str = "确认",
        message: str = "确定要执行此操作吗？",
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="dialog-title")
        yield Static(self._message, classes="dialog-message")
        with Static(classes="dialog-buttons"):
            yield Button("确认", variant="success", id="btn-confirm")
            yield Button("取消", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
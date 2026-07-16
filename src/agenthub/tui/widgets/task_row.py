from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


STATUS_ICONS = {
    "open": "🟢",
    "in_progress": "🟡",
    "claimed": "🟡",
    "submitted": "🔵",
    "completed": "✅",
    "cancelled": "⚪",
    "pending": "⏳",
    "ready_for_preparation": "🟠",
}

STATUS_COLORS = {
    "open": "green",
    "in_progress": "yellow",
    "claimed": "yellow",
    "submitted": "blue",
    "completed": "dim",
    "cancelled": "dim",
    "pending": "orange1",
    "ready_for_preparation": "orange1",
}

ROLE_ABBR = {
    "architect": "arch",
    "contributor": "contrib",
    "executor": "exec",
    "reviewer": "review",
    "tester": "test",
    "librarian": "lib",
    "observer": "obs",
}


class TaskRow(Widget):
    """单行任务卡片，两行布局：标题行 + 元信息行。"""

    DEFAULT_CSS = """
    TaskRow {
        height: 4;
        padding: 0 1;
        border-bottom: solid $panel;
    }

    TaskRow:hover {
        background: $panel;
    }

    TaskRow.focused {
        background: $boost;
        border-left: thick $accent;
    }

    TaskRow #row-title {
        height: 2;
        text-overflow: ellipsis;
        overflow: hidden;
    }

    TaskRow #row-meta {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        task: dict,
        icon: str,
        title: str,
        role: str,
        status: str,
        reward: int,
    ) -> None:
        super().__init__()
        self._task_data = task
        self._icon = icon
        self._title = title
        self._role = role
        self._status = status
        self._reward = reward

    def compose(self) -> ComposeResult:
        color = STATUS_COLORS.get(self._status, "white")
        role_short = ROLE_ABBR.get(self._role, self._role[:6] if self._role else "?")
        yield Static(
            f"{self._icon} {self._title}",
            id="row-title",
        )
        yield Static(
            f"[{color}]{self._status}[/{color}]  [{role_short}]  💰{self._reward}",
            id="row-meta",
        )

    @property
    def task(self) -> dict:
        return self._task_data

    def update_data(self, task: dict) -> None:
        self._task_data = task
        status = task.get("status", "")
        self._icon = STATUS_ICONS.get(status, "●")
        self._title = task.get("title", "Untitled")
        self._role = task.get("required_role", "")
        self._status = status
        self._reward = task.get("reward", 0)
        try:
            color = STATUS_COLORS.get(self._status, "white")
            role_short = ROLE_ABBR.get(self._role, self._role[:6] if self._role else "?")
            self.query_one("#row-title", Static).update(
                f"{self._icon} {self._title}"
            )
            self.query_one("#row-meta", Static).update(
                f"[{color}]{self._status}[/{color}]  [{role_short}]  💰{self._reward}"
            )
        except Exception:
            pass

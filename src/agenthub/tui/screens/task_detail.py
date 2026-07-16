from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class TaskDetailScreen(Widget):
    """Task detail panel — embedded as a Widget, not a Screen."""

    DEFAULT_CSS = """
    TaskDetailScreen {
        layout: vertical;
        height: 100%;
        padding: 1 2;
    }

    TaskDetailScreen #detail-title {
        text-style: bold;
        text-align: left;
        margin-bottom: 1;
    }

    TaskDetailScreen #detail-meta {
        color: $text-muted;
        margin-bottom: 1;
    }

    TaskDetailScreen #detail-description {
        height: 1fr;
        overflow-y: auto;
    }

    TaskDetailScreen #detail-empty {
        color: $text-muted;
        text-align: center;
        padding: 4;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_task: Optional[dict] = None

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-title")
        yield Static("", id="detail-meta")
        yield Static("← 选择左侧任务查看详情", id="detail-empty")
        yield Static("", id="detail-description")

    def show_task(self, task: dict) -> None:
        self._current_task = task

        try:
            title_w = self.query_one("#detail-title", Static)
            meta_w = self.query_one("#detail-meta", Static)
            desc_w = self.query_one("#detail-description", Static)
            empty_w = self.query_one("#detail-empty", Static)
        except Exception:
            return

        empty_w.display = False

        title_w.update(f"[bold]{task.get('title', 'Untitled')}[/bold]")

        status = task.get("status", "unknown")
        role = task.get("required_role", "unknown")
        reward = task.get("reward", 0)
        assignee = task.get("assignee") or "无"
        track = task.get("track") or "-"
        deps = task.get("dependencies", [])
        dep_str = ", ".join(str(d) for d in deps) if deps else "无"
        bounty_id = task.get("id", "")

        meta_w.update(
            f"ID: [dim]{bounty_id}[/dim]\n"
            f"状态: [bold]{status}[/bold] │ 角色: [bold]{role}[/bold] │ "
            f"奖励: [bold]{reward}[/bold] │ 认领者: {assignee}\n"
            f"轨道: {track} │ 依赖: {dep_str}"
        )

        description = task.get("description", "")
        if description:
            try:
                desc_w.update(Markdown(description))
            except Exception:
                desc_w.update(description)
        else:
            desc_w.update("[dim]无描述[/dim]")

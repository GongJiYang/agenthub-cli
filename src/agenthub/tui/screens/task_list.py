from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Static

from ..widgets.task_row import TaskRow

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

ROLE_FILTERS = ["all", "architect", "contributor", "executor", "reviewer", "tester"]
STATUS_FILTERS = ["all", "open", "in_progress", "submitted", "completed", "cancelled"]


class TaskListScreen(Widget):
    """Task list panel — embedded as a Widget, not a Screen."""

    BINDINGS = [
        Binding("up", "cursor_up", "上移", show=False),
        Binding("down", "cursor_down", "下移", show=False),
        Binding("enter", "select_task", "选择", show=False),
    ]

    DEFAULT_CSS = """
    TaskListScreen {
        layout: vertical;
        height: 100%;
    }

    TaskListScreen #search-input {
        margin: 0 1;
        height: 3;
    }

    TaskListScreen #filter-label {
        height: 1;
        margin: 0 1;
        color: $text-muted;
    }

    TaskListScreen #task-scroll {
        height: 1fr;
    }

    TaskRow {
        height: 4;
        padding: 0 1;
    }
    """

    def __init__(self, *args, repos: list[str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tasks: list[dict] = []
        self._filtered_tasks: list[dict] = []
        self._search_query: str = ""
        self._role_filter_idx: int = 0
        self._status_filter_idx: int = 0
        self._repo_filter_idx: int = 0
        self._repos: list[str] = repos or ["all"]
        self._selected_index: int = 0
        self._filter_mode: int = 0

    def compose(self) -> ComposeResult:
        yield Input(placeholder="搜索任务... (按 / 聚焦)", id="search-input")
        yield Static("加载中...", id="filter-label")
        yield VerticalScroll(id="task-scroll")

    def set_repos(self, repos: list[str]) -> None:
        self._repos = ["all"] + repos
        self._apply_filters()

    def update_tasks(self, tasks: list[dict]) -> None:
        self._tasks = tasks
        self._apply_filters()

    def _apply_filters(self) -> None:
        role_filter = ROLE_FILTERS[self._role_filter_idx]
        status_filter = STATUS_FILTERS[self._status_filter_idx]
        repo_filter = (
            self._repos[self._repo_filter_idx]
            if self._repo_filter_idx < len(self._repos)
            else "all"
        )

        filtered = self._tasks
        if repo_filter != "all":
            filtered = [t for t in filtered if t.get("repo_name", "") == repo_filter]
        if role_filter != "all":
            filtered = [
                t for t in filtered if t.get("required_role", "").lower() == role_filter
            ]
        if status_filter != "all":
            filtered = [
                t for t in filtered if t.get("status", "").lower() == status_filter
            ]
        if self._search_query:
            q = self._search_query.lower()
            filtered = [
                t
                for t in filtered
                if q in t.get("title", "").lower()
                or q in t.get("description", "").lower()
            ]

        self._filtered_tasks = filtered
        self._render_tasks()

    def _render_tasks(self) -> None:
        try:
            scroll = self.query_one("#task-scroll", VerticalScroll)
        except Exception:
            return

        try:
            filter_label = self.query_one("#filter-label", Static)
            repo = (
                self._repos[self._repo_filter_idx]
                if self._repo_filter_idx < len(self._repos)
                else "all"
            )
            role = ROLE_FILTERS[self._role_filter_idx]
            status = STATUS_FILTERS[self._status_filter_idx]
            filter_label.update(
                f"仓库: {repo} │ 角色: {role} │ 状态: {status} │ 共 {len(self._filtered_tasks)} 项"
            )
        except Exception:
            pass

        # 构建新的 widget 列表，批量替换
        def _rebuild() -> None:
            scroll.remove_children()
            if not self._filtered_tasks:
                scroll.mount(Static("  没有可用任务，请检查服务器连接或登录状态"))
                return
            rows = []
            for i, task in enumerate(self._filtered_tasks):
                icon = STATUS_ICONS.get(task.get("status", ""), "●")
                title = task.get("title", "Untitled")
                role_str = task.get("required_role", "")
                status_str = task.get("status", "")
                reward = task.get("reward", 0)
                row = TaskRow(task, icon, title, role_str, status_str, reward)
                if i == self._selected_index:
                    row.add_class("focused")
                rows.append(row)
            scroll.mount(*rows)

        self.call_after_refresh(_rebuild)

    def get_selected_bounty_id(self) -> Optional[str]:
        if not self._filtered_tasks:
            return None
        idx = max(0, min(self._selected_index, len(self._filtered_tasks) - 1))
        return str(self._filtered_tasks[idx].get("id", ""))

    def get_selected_task(self) -> Optional[dict]:
        if not self._filtered_tasks:
            return None
        idx = max(0, min(self._selected_index, len(self._filtered_tasks) - 1))
        return self._filtered_tasks[idx]

    def focus_search(self) -> None:
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def cycle_filter(self) -> None:
        self._filter_mode = (self._filter_mode + 1) % 3
        if self._filter_mode == 0:
            self._repo_filter_idx = (self._repo_filter_idx + 1) % max(1, len(self._repos))
        elif self._filter_mode == 1:
            self._role_filter_idx = (self._role_filter_idx + 1) % len(ROLE_FILTERS)
        else:
            self._status_filter_idx = (self._status_filter_idx + 1) % len(STATUS_FILTERS)
        self._apply_filters()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search_query = event.value
            self._apply_filters()

    def action_cursor_up(self) -> None:
        if self._selected_index > 0:
            self._selected_index -= 1
            self._render_tasks()
            # 延迟到 widget 重建完成后再更新详情
            self.call_after_refresh(self.action_select_task)

    def action_cursor_down(self) -> None:
        if self._selected_index < len(self._filtered_tasks) - 1:
            self._selected_index += 1
            self._render_tasks()
            self.call_after_refresh(self.action_select_task)

    def action_select_task(self) -> None:
        task = self.get_selected_task()
        if not task:
            return
        try:
            from .task_detail import TaskDetailScreen
            detail = self.app.query_one("#task-detail", TaskDetailScreen)
            detail.show_task(task)
        except Exception as e:
            self.app.notify(f"无法显示详情: {e}", severity="warning")

    def on_key(self, event) -> None:
        key = event.key
        if key == "enter":
            event.prevent_default()
            self.action_select_task()
        elif key == "up" or key == "k":
            event.prevent_default()
            self.action_cursor_up()
        elif key == "down" or key == "j":
            event.prevent_default()
            self.action_cursor_down()

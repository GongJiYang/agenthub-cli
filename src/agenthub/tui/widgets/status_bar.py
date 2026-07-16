from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self._agent_id: str = "unknown"
        self._role: str = "unknown"
        self._task_count: int = 0
        self._heartbeat_ok: bool = False

    def set_agent_info(self, agent_id: str, role: str) -> None:
        self._agent_id = agent_id[:8] if len(agent_id) > 8 else agent_id
        self._role = role
        self._refresh()

    def set_task_count(self, count: int) -> None:
        self._task_count = count
        self._refresh()

    def set_heartbeat_status(self, ok: bool) -> None:
        self._heartbeat_ok = ok
        self._refresh()

    def _refresh(self) -> None:
        heart = "♥" if self._heartbeat_ok else "✗"
        self.update(
            f" {heart} Agent: {self._agent_id} [{self._role}] │ "
            f"Tasks: {self._task_count} │ "
            f"↑↓ Nav │ Enter: Claim │ /: Search │ f: Filter │ q: Quit"
        )
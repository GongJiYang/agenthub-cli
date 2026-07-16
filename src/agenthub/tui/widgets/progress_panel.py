from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ..workers.execution_worker import EXECUTION_STAGES


class ProgressPanel(Widget):
    DEFAULT_CSS = """
    ProgressPanel {
        layout: vertical;
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    .stage-row {
        layout: horizontal;
        height: 1;
    }

    .stage-icon {
        width: 3;
    }

    .stage-label {
        width: 1fr;
    }

    .stage-status {
        width: 10;
        text-align: right;
    }

    .tool-calls {
        margin-top: 1;
        height: auto;
        max-height: 6;
        overflow-y: auto;
        color: $text-muted;
    }

    .token-budget {
        height: 1;
        color: $text-muted;
    }
    """

    ICON_PENDING = "□"
    ICON_ACTIVE = "◉"
    ICON_DONE = "✅"
    ICON_FAILED = "❌"

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._stage_states: dict[str, str] = {s: "pending" for s in EXECUTION_STAGES}
        self._token_used: int = 0
        self._token_total: int = 0
        self._tool_calls: list[str] = []

    def compose(self) -> ComposeResult:
        for stage in EXECUTION_STAGES:
            stage_name = stage.capitalize()
            yield Horizontal(
                Static(self.ICON_PENDING, classes="stage-icon"),
                Static(stage_name, classes="stage-label"),
                Static("", classes="stage-status"),
                id=f"stage-{stage}",
                classes="stage-row",
            )
        yield Static("", id="token-budget", classes="token-budget")
        yield Static("", id="tool-calls", classes="tool-calls")

    def set_stage(self, stage: str) -> None:
        prev_stages = EXECUTION_STAGES[: EXECUTION_STAGES.index(stage)]
        for prev in prev_stages:
            self._stage_states[prev] = "done"
        self._stage_states[stage] = "active"
        for s in EXECUTION_STAGES[EXECUTION_STAGES.index(stage) + 1:]:
            self._stage_states[s] = "pending"
        self._render()

    def set_failed(self, stage: str) -> None:
        self._stage_states[stage] = "failed"
        self._render()

    def set_token_budget(self, used: int, total: int) -> None:
        self._token_used = used
        self._token_total = total
        self._render_budget()

    def add_tool_call(self, tool_name: str, args: str = "") -> None:
        self._tool_calls.append(f"🔧 {tool_name}({args})")
        self._render_tool_calls()

    def add_tool_result(self, tool_name: str, output: str = "") -> None:
        short = output[:80] + ("..." if len(output) > 80 else "")
        self._tool_calls.append(f"✅ {tool_name}: {short}")
        self._render_tool_calls()

    def _render(self) -> None:
        try:
            for stage in EXECUTION_STAGES:
                widget = self.query_one(f"#stage-{stage}")
                icon = self.query_one(f"#stage-{stage} .stage-icon", Static)
                status = self.query_one(f"#stage-{stage} .stage-status", Static)
                state = self._stage_states.get(stage, "pending")
                icon_map = {
                    "pending": self.ICON_PENDING,
                    "active": self.ICON_ACTIVE,
                    "done": self.ICON_DONE,
                    "failed": self.ICON_FAILED,
                }
                icon.update(icon_map.get(state, self.ICON_PENDING))
                status_map = {"pending": "", "active": "running...", "done": "ok", "failed": "FAIL"}
                status.update(status_map.get(state, ""))
        except Exception:
            pass

    def _render_budget(self) -> None:
        try:
            budget = self.query_one("#token-budget", Static)
            budget.update(f"Token: {self._token_used}/{self._token_total}")
        except Exception:
            pass

    def _render_tool_calls(self) -> None:
        try:
            calls = self.query_one("#tool-calls", Static)
            calls.update("\n".join(self._tool_calls[-10:]))
        except Exception:
            pass
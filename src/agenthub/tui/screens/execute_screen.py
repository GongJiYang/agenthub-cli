from __future__ import annotations

from typing import Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Static

from ..widgets.confirm_dialog import ConfirmDialog
from ..widgets.log_viewer import LogViewer
from ..widgets.progress_panel import ProgressPanel
from ..workers.execution_worker import (
    ExecutionCancelFlag,
    ExecutionComplete,
    ExecutionError,
    ExecutionOutput,
    ExecutionStage,
    run_execution_pipeline,
)


class ExecuteScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "取消执行", show=True),
    ]

    DEFAULT_CSS = """
    ExecuteScreen {
        layout: vertical;
    }

    ExecuteScreen .progress-area {
        height: auto;
        margin-bottom: 1;
    }

    ExecuteScreen .log-area {
        height: 1fr;
    }

    ExecuteScreen .action-bar {
        height: 3;
        layout: horizontal;
        align: center middle;
        background: $surface;
    }

    ExecuteScreen Button {
        margin: 0 1;
    }

    ExecuteScreen .status-label {
        height: 1;
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        bounty_id: str,
        api_base_url: str,
        auth: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._bounty_id = bounty_id
        self._api_base_url = api_base_url
        self._auth = auth
        self._cancel_flag = ExecutionCancelFlag()
        self._executing = False
        self._completed = False

    def compose(self) -> ComposeResult:
        yield Static(f"执行任务: {self._bounty_id}", classes="status-label")
        yield ProgressPanel(classes="progress-area")
        yield LogViewer(classes="log-area")
        with Static(classes="action-bar"):
            yield Button("取消", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.app.push_screen(
            ConfirmDialog(
                title="确认执行",
                message=f"确定要执行任务 {self._bounty_id[:8]}...?\n\n此操作将启动 Claude Code 执行编程任务。",
            ),
            callback=self._on_confirm,
        )

    def _on_confirm(self, confirmed: bool) -> None:
        if confirmed:
            self._start_execution()
        else:
            self.app.pop_screen()

    def _start_execution(self) -> None:
        self._executing = True
        self._cancel_flag.clear()
        log = self.query_one(LogViewer)
        log.write_line("⏳ 开始执行...", severity="info")
        self._run_execution()

    @work(name="execution", group="execution", exclusive=True)
    async def _run_execution(self) -> None:
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None,
            run_execution_pipeline,
            self.app,
            self._bounty_id,
            self._api_base_url,
            self._auth,
            self._cancel_flag,
        )

    def on_execution_stage(self, event: ExecutionStage) -> None:
        progress = self.query_one(ProgressPanel)
        progress.set_stage(event.stage)
        log = self.query_one(LogViewer)
        stage_names = {"claim": "认领验证", "context": "构建上下文", "execute": "执行推理", "validate": "验证结果", "submit": "提交成果"}
        log.write_line(f"▶ {stage_names.get(event.stage, event.stage)}", severity="info")

    def on_execution_output(self, event: ExecutionOutput) -> None:
        log = self.query_one(LogViewer)
        log.write_line(event.text, severity="info")

    def on_execution_error(self, event: ExecutionError) -> None:
        self._executing = False
        progress = self.query_one(ProgressPanel)
        progress.set_failed("execute")
        log = self.query_one(LogViewer)
        log.write_line(f"❌ {event.message}", severity="error")

    def on_execution_complete(self, event: ExecutionComplete) -> None:
        self._executing = False
        self._completed = True
        log = self.query_one(LogViewer)
        if event.success:
            log.write_line(f"✅ {event.message}", severity="success")
        else:
            log.write_line(f"❌ {event.message}", severity="error")

        action_bar = self.query_one(".action-bar", Static)
        action_bar.query(Button).remove()
        if event.success:
            action_bar.mount(Button("返回列表", variant="success", id="btn-back"))
        else:
            action_bar.mount(Button("返回列表", variant="default", id="btn-back"))
            action_bar.mount(Button("重试", variant="warning", id="btn-retry"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self._cancel_execution()
        elif event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-retry":
            self._start_execution()

    def action_cancel(self) -> None:
        self._cancel_execution()

    def _cancel_execution(self) -> None:
        if self._executing:
            self._cancel_flag.set()
            log = self.query_one(LogViewer)
            log.write_line("⚠ 正在取消...", severity="warning")
        else:
            self.app.pop_screen()
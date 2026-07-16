from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Static

from ..widgets.log_viewer import LogViewer
from ..bridges.ui_chat_bridge import UIChatBridge
from ...models import ToolCall


class ChatScreen(Screen):
    BINDINGS = [
        Binding("escape", "exit_chat", "退出对话", show=True),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
    }

    ChatScreen .chat-header {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    ChatScreen .chat-messages {
        height: 1fr;
    }

    ChatScreen .chat-input-area {
        height: 3;
        layout: vertical;
        border-top: solid $primary;
    }

    ChatScreen #chat-input {
        height: 1fr;
    }

    ChatScreen .chat-cmd-hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        bounty_id: Optional[str] = None,
        api_base_url: str = "",
        auth: object | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._bounty_id = bounty_id
        self._api_base_url = api_base_url
        self._auth = auth
        self._bridge: Optional[UIChatBridge] = None

    def compose(self) -> ComposeResult:
        header_text = f"💬 对话模式 ({self._bounty_id[:8]}...)" if self._bounty_id else "💬 对话模式"
        yield Static(header_text, classes="chat-header")
        yield LogViewer(classes="chat-messages")
        with Vertical(classes="chat-input-area"):
            yield Input(placeholder="输入消息... (/exit 退出, /clear 清空)", id="chat-input")
            yield Static("/exit 退出  /clear 清空  /save 保存历史", classes="chat-cmd-hint")

    def on_mount(self) -> None:
        log = self.query_one(LogViewer)
        log.write_line("对话模式已启动，输入消息开始对话。", severity="info")
        if self._bounty_id:
            log.write_line(f"关联任务: {self._bounty_id}", severity="info")

        self._bridge = UIChatBridge(
            on_token=lambda text: self.app.call_from_thread(self._on_token, text),
            on_newline=lambda: self.app.call_from_thread(self._on_newline),
            on_tool_call=lambda tc: self.app.call_from_thread(self._on_tool_call, tc),
            on_tool_result=lambda tc, r: self.app.call_from_thread(self._on_tool_result, tc, r),
            on_error=lambda msg: self.app.call_from_thread(self._on_error, msg),
            on_complete=lambda: self.app.call_from_thread(self._on_complete),
        )

    def on_unmount(self) -> None:
        if self._bridge:
            self._bridge.stop_session()

    def _on_token(self, text: str) -> None:
        log = self.query_one(LogViewer)
        log.write(text)

    def _on_newline(self) -> None:
        log = self.query_one(LogViewer)
        log.write_line("")

    def _on_tool_call(self, tc: ToolCall) -> None:
        log = self.query_one(LogViewer)
        log.write_line(f"🔧 调用工具: {tc.name}", severity="info")

    def _on_tool_result(self, tc: ToolCall, result: str) -> None:
        log = self.query_one(LogViewer)
        summary = result[:200] + ("..." if len(result) > 200 else "")
        log.write_line(f"✅ {tc.name}: {summary}", severity="info")

    def _on_error(self, msg: str) -> None:
        log = self.query_one(LogViewer)
        log.write_line(f"❌ {msg}", severity="error")
        self._set_input_enabled(True)

    def _on_complete(self) -> None:
        self._set_input_enabled(True)

    def _set_input_enabled(self, enabled: bool) -> None:
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.disabled = not enabled
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        text = event.value.strip()
        if not text:
            return

        event.input.value = ""
        log = self.query_one(LogViewer)

        if text.startswith("/"):
            self._handle_command(text, log)
            return

        log.write_line(f"🧑 {text}", severity="info")
        self._set_input_enabled(False)
        self._send_message(text)

    def _handle_command(self, cmd: str, log: LogViewer) -> None:
        if cmd == "/exit":
            self.action_exit_chat()
        elif cmd == "/clear":
            log.clear_log()
            log.write_line("对话已清空", severity="info")
        elif cmd == "/save":
            log.write_line("⚠ 保存历史功能待实现", severity="warning")
        else:
            log.write_line(f"未知命令: {cmd}", severity="error")

    def _send_message(self, text: str) -> None:
        if self._bridge is None:
            log = self.query_one(LogViewer)
            log.write_line("❌ 对话桥接未初始化", severity="error")
            self._set_input_enabled(True)
            return

        config = None
        auth = self._auth

        try:
            from ...config import load_config
            config = load_config()
        except Exception:
            pass

        if not self._bridge.is_running():
            self._bridge.start_session(
                config=config,
                auth=auth,
                bounty_id=self._bounty_id,
            )

        self._bridge.send_user_message(text)

    def action_exit_chat(self) -> None:
        if self._bridge:
            self._bridge.stop_session()
        self.app.pop_screen()
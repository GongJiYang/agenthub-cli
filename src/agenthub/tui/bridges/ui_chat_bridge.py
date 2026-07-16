from __future__ import annotations

import threading
from typing import Callable, Optional

from ..bridges.ui_stream_printer import UIStreamPrinter
from ...auth import AuthModule
from ...config import AppConfig, load_config
from ...http_client import AgentHubClient
from ...models import ChatSession, ToolCall


class ChatCancelFlag:
    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


class UIChatBridge:
    def __init__(
        self,
        on_token: Optional[Callable[[str], None]] = None,
        on_newline: Optional[Callable[[], None]] = None,
        on_tool_call: Optional[Callable[[ToolCall], None]] = None,
        on_tool_result: Optional[Callable[[ToolCall, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_token = on_token or (lambda _: None)
        self._on_newline = on_newline or (lambda: None)
        self._on_tool_call = on_tool_call or (lambda _: None)
        self._on_tool_result = on_tool_result or (lambda _tc, _r: None)
        self._on_error = on_error or (lambda _m: None)
        self._on_complete = on_complete or (lambda: None)

        self._printer = UIStreamPrinter(
            on_token=self._on_token,
            on_newline=self._on_newline,
            on_tool_call=self._on_tool_call,
            on_tool_result=self._on_tool_result,
        )

        self._cancel_flag = ChatCancelFlag()
        self._thread: Optional[threading.Thread] = None
        self._runner: Optional[object] = None
        self._config: Optional[AppConfig] = None
        self._auth: Optional[AuthModule] = None
        self._client: Optional[AgentHubClient] = None
        self._session: Optional[ChatSession] = None

    def start_session(
        self,
        config: Optional[AppConfig] = None,
        auth: Optional[AuthModule] = None,
        bounty_id: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        show_tools: bool = True,
    ) -> None:
        self._config = config or load_config()
        self._auth = auth or AuthModule()
        self._cancel_flag.clear()

        try:
            from ...chat_runner import ChatRunner
            self._runner = ChatRunner(
                config=self._config,
                auth=self._auth,
                bounty_id=bounty_id,
                model=model,
                show_tools=show_tools,
                save_path=None,
                printer=self._printer,
            )
            self._session = self._runner._session
        except ImportError:
            self._on_error("ChatRunner 不可用，请确认依赖已安装")

    def send_user_message(self, text: str) -> None:
        if self._cancel_flag.is_set():
            return
        if self._runner is None:
            self.start_session()

        if self._runner is None:
            self._on_error("ChatRunner 初始化失败")
            return

        if self._runner._session is None:
            try:
                self._runner._session = self._runner._init_session()
            except Exception as e:
                self._on_error(f"初始化会话失败: {e}")
                return

        def _run():
            try:
                self._runner._send_message(text)
            except Exception as e:
                self._on_error(f"发送消息失败: {e}")
            finally:
                self._on_complete()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_flag.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop_session(self) -> None:
        self.cancel()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
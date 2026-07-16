from __future__ import annotations

from typing import Callable, Optional

from ...stream_printer import StreamPrinter
from ...models import ToolCall


class UIStreamPrinter(StreamPrinter):
    def __init__(
        self,
        on_token: Optional[Callable[[str], None]] = None,
        on_newline: Optional[Callable[[], None]] = None,
        on_tool_call: Optional[Callable[[ToolCall], None]] = None,
        on_tool_result: Optional[Callable[[ToolCall, str], None]] = None,
        on_tool_denied: Optional[Callable[[ToolCall], None]] = None,
        on_interrupted: Optional[Callable[[], None]] = None,
        on_welcome: Optional[Callable[[str, Optional[str]], None]] = None,
        show_tools: bool = True,
    ) -> None:
        super().__init__(show_tools=show_tools)
        self._on_token = on_token or (lambda _: None)
        self._on_newline = on_newline or (lambda: None)
        self._on_tool_call = on_tool_call or (lambda _: None)
        self._on_tool_result = on_tool_result or (lambda _tc, _r: None)
        self._on_tool_denied = on_tool_denied or (lambda _: None)
        self._on_interrupted = on_interrupted or (lambda: None)
        self._on_welcome = on_welcome or (lambda _m, _b: None)

    def print_token(self, token: str) -> None:
        self._on_token(token)

    def print_newline(self) -> None:
        self._on_newline()

    def print_tool_call(self, tool_call: ToolCall) -> None:
        self._on_tool_call(tool_call)

    def print_tool_result(self, tool_call: ToolCall, result: str) -> None:
        self._on_tool_result(tool_call, result)

    def print_tool_denied(self, tool_call: ToolCall) -> None:
        self._on_tool_denied(tool_call)

    def print_interrupted(self) -> None:
        self._on_interrupted()

    def print_welcome(self, mode: str, bounty_id: Optional[str] = None) -> None:
        self._on_welcome(mode, bounty_id)
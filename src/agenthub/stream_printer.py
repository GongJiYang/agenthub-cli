"""Stream_Printer：将 AI 流式响应实时打印到终端的组件。"""
from __future__ import annotations

import json
import sys
from typing import IO

from .models import ToolCall


class StreamPrinter:
    """负责将 AI 流式响应和工具调用信息打印到终端。"""

    def __init__(self, show_tools: bool = True, out: IO[str] = sys.stdout) -> None:
        self._show_tools = show_tools
        self._out = out

    def print_token(self, token: str) -> None:
        """逐 token 打印到输出流并立即 flush。"""
        self._out.write(token)
        self._out.flush()

    def print_newline(self) -> None:
        """响应完成后打印换行符。"""
        self._out.write("\n")
        self._out.flush()

    def print_tool_call(self, tool_call: ToolCall) -> None:
        """打印工具调用信息（show_tools=True 时）。
        格式：[工具] <name>: <args_summary>
        """
        if not self._show_tools:
            return
        args_summary = self._summarize_args(tool_call.args)
        self._out.write(f"\n[工具] {tool_call.name}: {args_summary}\n")
        self._out.flush()

    def print_tool_result(self, tool_call: ToolCall, result: str) -> None:
        """打印工具结果摘要（show_tools=True 时，前 200 字符）。"""
        if not self._show_tools:
            return
        summary = result[:200] + ("..." if len(result) > 200 else "")
        self._out.write(f"[结果] {summary}\n")
        self._out.flush()

    def print_tool_denied(self, tool_call: ToolCall) -> None:
        """打印拒绝信息（无论 show_tools 值）。
        格式：[拒绝] <name>: permission_denied
        """
        self._out.write(f"\n[拒绝] {tool_call.name}: permission_denied\n")
        self._out.flush()

    def print_interrupted(self) -> None:
        """打印中断提示。"""
        self._out.write("\n[已中断]\n")
        self._out.flush()

    def print_welcome(self, mode: str, bounty_id: str | None = None) -> None:
        """打印欢迎信息。"""
        if mode == "bounty" and bounty_id:
            self._out.write(f"\n🤖 AgentHub Chat — Bounty 模式 [{bounty_id}]\n")
            self._out.write("可用命令：/exit  /save  /clear  /submit\n\n")
        else:
            self._out.write("\n🤖 AgentHub Chat — 独立对话模式\n")
            self._out.write("可用命令：/exit  /save  /clear\n\n")
        self._out.flush()

    # ── 内部辅助 ──────────────────────────────────────

    @staticmethod
    def _summarize_args(args: dict) -> str:
        """将工具参数序列化为简短摘要字符串。"""
        try:
            s = json.dumps(args, ensure_ascii=False)
            return s[:100] + ("..." if len(s) > 100 else "")
        except Exception:
            return str(args)[:100]

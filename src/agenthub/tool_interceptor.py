from __future__ import annotations

import fnmatch
from typing import Any, Callable

from .models import SkillConfig, ToolCall, ToolResult
from .trace_writer import TraceWriter

# 需要路径校验的文件操作工具
_FILE_TOOLS = {"read_file", "write_file"}


class ToolInterceptor:
    def __init__(
        self,
        skill_config: SkillConfig,
        trace_writer: TraceWriter,
        executor: Callable[[ToolCall], Any] | None = None,
    ) -> None:
        self._skill_config = skill_config
        self._trace_writer = trace_writer
        self._executor = executor

    def intercept(self, tool_call: ToolCall) -> ToolResult:
        """
        1. 校验工具名是否在白名单
        2. 若为文件操作工具，校验 path 是否匹配 path_rules
        3. 通过校验：调用 executor（若有）并返回 ToolResult(allowed=True)
        4. 不通过：返回 ToolResult(output="permission_denied", allowed=False)
        5. 每次调用后将 tool_call 和 result 传给 trace_writer.record()
        """
        allowed = self._is_allowed(tool_call)

        if allowed:
            if self._executor is not None:
                output = self._executor(tool_call)
            else:
                output = None
            result = ToolResult(
                tool_call_id=tool_call.id,
                output=output,
                allowed=True,
            )
        else:
            result = ToolResult(
                tool_call_id=tool_call.id,
                output="permission_denied",
                allowed=False,
            )

        self._trace_writer.record(tool_call, result)
        return result

    # ------------------------------------------------------------------
    def _is_allowed(self, tool_call: ToolCall) -> bool:
        # 白名单校验
        if tool_call.name not in self._skill_config.tool_whitelist:
            return False

        # 文件操作工具需额外校验路径
        if tool_call.name in _FILE_TOOLS:
            path = tool_call.args.get("path", "")
            if not self._path_allowed(path):
                return False

        return True

    def _path_allowed(self, path: str) -> bool:
        """检查 path 是否匹配 path_rules 中的任意 glob 规则。"""
        for rule in self._skill_config.path_rules:
            if fnmatch.fnmatch(path, rule):
                return True
        return False

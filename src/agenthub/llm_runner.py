from __future__ import annotations

import json
import subprocess
from typing import Any

from .models import Context, LLMConfig, LLMOutput, ToolCall
from .tool_interceptor import ToolInterceptor


class LLMRunner:
    def __init__(self, config: LLMConfig, interceptor: ToolInterceptor) -> None:
        self._config = config
        self._interceptor = interceptor

    def run(self, context: Context) -> LLMOutput:
        if self._config.provider == "claude-code":
            return self._run_claude_code(context)
        elif self._config.provider == "anthropic":
            return self._run_anthropic_api(context)
        else:
            return LLMOutput(
                status="failed",
                content={},
                raw_text=f"Unknown provider: {self._config.provider}",
            )

    # ------------------------------------------------------------------
    # claude-code 模式：通过 `claude --print --output-format json` 子进程
    # ------------------------------------------------------------------

    def _run_claude_code(self, context: Context) -> LLMOutput:
        prompt = self._build_prompt(context)

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        while True:
            input_payload = json.dumps({"messages": messages})

            try:
                proc = subprocess.Popen(
                    ["claude", "--print", "--output-format", "json"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, _ = proc.communicate(input=input_payload)
            except FileNotFoundError:
                return LLMOutput(
                    status="failed",
                    content={},
                    raw_text="claude executable not found",
                )

            raw_text = stdout.strip()

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                return LLMOutput(status="failed", content={}, raw_text=raw_text)

            # 检查是否包含 tool_call
            tool_calls = self._extract_tool_calls_from_claude(data)
            if tool_calls:
                # 将 assistant 消息追加到对话历史
                messages.append({"role": "assistant", "content": data.get("content", raw_text)})

                # 处理每个 tool_call
                tool_results = []
                for tc in tool_calls:
                    result = self._interceptor.intercept(tc)
                    tool_results.append({
                        "tool_call_id": result.tool_call_id,
                        "output": result.output,
                        "allowed": result.allowed,
                    })

                # 将工具结果追加到对话历史
                messages.append({"role": "tool", "content": json.dumps(tool_results)})
                continue

            # 检查是否包含 status: submitted
            status = data.get("status")
            if status == "submitted":
                return LLMOutput(
                    status="submitted",
                    content=data,
                    raw_text=raw_text,
                )

            if status is None:
                return LLMOutput(status="failed", content=data, raw_text=raw_text)

            # status 为其他值（如 failed）
            return LLMOutput(
                status="failed",
                content=data,
                raw_text=raw_text,
            )

    def _extract_tool_calls_from_claude(self, data: dict[str, Any]) -> list[ToolCall]:
        """从 claude JSON 输出中提取 tool_call 列表。"""
        tool_calls: list[ToolCall] = []
        content = data.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.get("id", ""),
                            name=block.get("name", ""),
                            args=block.get("input", {}),
                        )
                    )
        elif isinstance(data.get("tool_calls"), list):
            for tc in data["tool_calls"]:
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        args=tc.get("args", {}),
                    )
                )
        return tool_calls

    # ------------------------------------------------------------------
    # anthropic API 模式：使用 anthropic Python SDK
    # ------------------------------------------------------------------

    def _run_anthropic_api(self, context: Context) -> LLMOutput:
        try:
            import anthropic as anthropic_sdk
        except ImportError:
            return LLMOutput(
                status="failed",
                content={},
                raw_text="anthropic SDK not installed. Run: pip install anthropic",
            )

        client = anthropic_sdk.Anthropic(api_key=self._config.api_key)

        system_prompt = context.system_prompt
        user_content = self._build_prompt(context)

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

        while True:
            response = client.messages.create(
                model=self._config.model,
                max_tokens=8192,
                system=system_prompt,
                messages=messages,
            )

            # 收集 assistant 消息内容块
            assistant_content: list[dict[str, Any]] = []
            tool_calls: list[ToolCall] = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_calls.append(
                        ToolCall(id=block.id, name=block.name, args=block.input)
                    )

            # 追加 assistant 消息
            messages.append({"role": "assistant", "content": assistant_content})

            if tool_calls:
                # 处理 tool_call，构造 tool_result 消息
                tool_result_content: list[dict[str, Any]] = []
                for tc in tool_calls:
                    result = self._interceptor.intercept(tc)
                    tool_result_content.append({
                        "type": "tool_result",
                        "tool_use_id": result.tool_call_id,
                        "content": str(result.output),
                    })

                messages.append({"role": "user", "content": tool_result_content})
                continue

            # 没有 tool_call，尝试从文本中解析最终输出
            raw_text = ""
            for block in response.content:
                if block.type == "text":
                    raw_text += block.text

            raw_text = raw_text.strip()

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                return LLMOutput(status="failed", content={}, raw_text=raw_text)

            status = data.get("status")
            if status == "submitted":
                return LLMOutput(status="submitted", content=data, raw_text=raw_text)

            return LLMOutput(status="failed", content=data, raw_text=raw_text)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _build_prompt(self, context: Context) -> str:
        """将 bounty 描述和文件内容组装为用户 prompt。"""
        parts: list[str] = [
            f"# Task\n{context.bounty.description}",
        ]

        if context.files:
            parts.append("\n# Files")
            for fc in context.files:
                if fc.missing:
                    parts.append(f"\n## {fc.path}\n⚠️ File not found, skipped.")
                else:
                    parts.append(f"\n## {fc.path}\n```\n{fc.content}\n```")

        return "\n".join(parts)

"""
Unit tests for LLMRunner.

Covers:
- claude-code mode: mock subprocess, verify tool_call routed to interceptor
- anthropic mode: mock anthropic.Anthropic, verify tool_call routed to interceptor
- status: submitted → correct LLMOutput returned
- tool_call rejected by interceptor (allowed=False) → execution continues
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agenthub.llm_runner import LLMRunner
from agenthub.models import (
    BountyDetail,
    Context,
    FileContent,
    LLMConfig,
    LLMOutput,
    SkillConfig,
    ToolCall,
    ToolResult,
)
from agenthub.tool_interceptor import ToolInterceptor
from agenthub.trace_writer import TraceWriter


# ── Fixtures ──────────────────────────────────────────────────────────

def _make_context() -> Context:
    bounty = BountyDetail(
        id="b1",
        role="contributor",
        title="Test Task",
        description="Implement feature X",
        files_to_read=["src/main.py"],
        token_budget=4096,
        status="claimed",
        repo_name="test-repo",
    )
    return Context(
        system_prompt="You are a helpful agent.",
        bounty=bounty,
        files=[FileContent(path="src/main.py", content="print('hello')")],
        token_budget=4096,
    )


def _make_interceptor(tmp_path=None) -> ToolInterceptor:
    skill_config = SkillConfig(
        role="contributor",
        system_prompt_template="",
        tool_whitelist=["read_file", "write_file"],
        path_rules=["src/**"],
        output_schema={},
    )
    import tempfile, pathlib
    trace_path = pathlib.Path(tempfile.mktemp(suffix=".jsonl"))
    trace_writer = TraceWriter(trace_path=trace_path)
    interceptor = ToolInterceptor(skill_config=skill_config, trace_writer=trace_writer)
    return interceptor


# ── claude-code mode tests ─────────────────────────────────────────────

class TestClaudeCodeMode:
    def _make_runner(self, interceptor: ToolInterceptor | None = None) -> LLMRunner:
        config = LLMConfig(provider="claude-code", model="claude-opus-4-5")
        if interceptor is None:
            interceptor = _make_interceptor()
        return LLMRunner(config=config, interceptor=interceptor)

    def test_submitted_output_returned(self):
        """When claude outputs status=submitted, LLMOutput(status=submitted) is returned."""
        runner = self._make_runner()
        final_output = {"status": "submitted", "summary": "done", "files_changed": []}

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (json.dumps(final_output), "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = runner.run(_make_context())

        assert result.status == "submitted"
        assert result.content["status"] == "submitted"

    def test_tool_call_routed_to_interceptor(self):
        """When claude outputs a tool_use block, interceptor.intercept() is called."""
        interceptor = _make_interceptor()
        interceptor.intercept = MagicMock(
            return_value=ToolResult(tool_call_id="tc1", output="file content", allowed=True)
        )
        runner = self._make_runner(interceptor=interceptor)

        tool_response = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tc1",
                    "name": "read_file",
                    "input": {"path": "src/main.py"},
                }
            ]
        }
        final_output = {"status": "submitted", "summary": "done", "files_changed": []}

        mock_proc_tool = MagicMock()
        mock_proc_tool.communicate.return_value = (json.dumps(tool_response), "")

        mock_proc_final = MagicMock()
        mock_proc_final.communicate.return_value = (json.dumps(final_output), "")

        with patch("subprocess.Popen", side_effect=[mock_proc_tool, mock_proc_final]):
            result = runner.run(_make_context())

        interceptor.intercept.assert_called_once()
        call_arg: ToolCall = interceptor.intercept.call_args[0][0]
        assert call_arg.name == "read_file"
        assert call_arg.id == "tc1"
        assert result.status == "submitted"

    def test_tool_call_rejected_continues(self):
        """When interceptor returns allowed=False, execution continues to next LLM turn."""
        interceptor = _make_interceptor()
        interceptor.intercept = MagicMock(
            return_value=ToolResult(tool_call_id="tc1", output="permission_denied", allowed=False)
        )
        runner = self._make_runner(interceptor=interceptor)

        tool_response = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tc1",
                    "name": "delete_file",
                    "input": {"path": "/etc/passwd"},
                }
            ]
        }
        final_output = {"status": "submitted", "summary": "done", "files_changed": []}

        mock_proc_tool = MagicMock()
        mock_proc_tool.communicate.return_value = (json.dumps(tool_response), "")

        mock_proc_final = MagicMock()
        mock_proc_final.communicate.return_value = (json.dumps(final_output), "")

        with patch("subprocess.Popen", side_effect=[mock_proc_tool, mock_proc_final]):
            result = runner.run(_make_context())

        interceptor.intercept.assert_called_once()
        assert result.status == "submitted"

    def test_invalid_json_returns_failed(self):
        """When claude outputs non-JSON, LLMOutput(status=failed) is returned."""
        runner = self._make_runner()

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("not valid json", "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = runner.run(_make_context())

        assert result.status == "failed"

    def test_missing_status_returns_failed(self):
        """When JSON has no status field, LLMOutput(status=failed) is returned."""
        runner = self._make_runner()
        output = {"summary": "done"}

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (json.dumps(output), "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = runner.run(_make_context())

        assert result.status == "failed"

    def test_claude_not_found_returns_failed(self):
        """When claude executable is missing, LLMOutput(status=failed) is returned."""
        runner = self._make_runner()

        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            result = runner.run(_make_context())

        assert result.status == "failed"
        assert "not found" in result.raw_text


# ── anthropic API mode tests ───────────────────────────────────────────

class TestAnthropicAPIMode:
    def _make_runner(self, interceptor: ToolInterceptor | None = None) -> LLMRunner:
        config = LLMConfig(
            provider="anthropic",
            model="claude-opus-4-5",
            api_key="test-key",
        )
        if interceptor is None:
            interceptor = _make_interceptor()
        return LLMRunner(config=config, interceptor=interceptor)

    def _make_text_block(self, text: str):
        block = MagicMock()
        block.type = "text"
        block.text = text
        return block

    def _make_tool_use_block(self, id: str, name: str, input: dict):
        block = MagicMock()
        block.type = "tool_use"
        block.id = id
        block.name = name
        block.input = input
        return block

    def _make_response(self, content_blocks: list):
        resp = MagicMock()
        resp.content = content_blocks
        return resp

    def _mock_anthropic_module(self, mock_client):
        """Return a fake anthropic module that yields mock_client on Anthropic()."""
        import sys
        mock_module = MagicMock()
        mock_module.Anthropic.return_value = mock_client
        return mock_module

    def test_submitted_output_returned(self):
        """When anthropic returns text with status=submitted, LLMOutput(status=submitted) is returned."""
        runner = self._make_runner()
        final_json = json.dumps({"status": "submitted", "summary": "done", "files_changed": []})

        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_response(
            [self._make_text_block(final_json)]
        )

        import sys
        with patch.dict("sys.modules", {"anthropic": self._mock_anthropic_module(mock_client)}):
            result = runner.run(_make_context())

        assert result.status == "submitted"

    def test_tool_call_routed_to_interceptor(self):
        """When anthropic returns tool_use block, interceptor.intercept() is called."""
        interceptor = _make_interceptor()
        interceptor.intercept = MagicMock(
            return_value=ToolResult(tool_call_id="tc1", output="file content", allowed=True)
        )
        runner = self._make_runner(interceptor=interceptor)

        final_json = json.dumps({"status": "submitted", "summary": "done", "files_changed": []})

        tool_response = self._make_response(
            [self._make_tool_use_block("tc1", "read_file", {"path": "src/main.py"})]
        )
        final_response = self._make_response([self._make_text_block(final_json)])

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [tool_response, final_response]

        import sys
        with patch.dict("sys.modules", {"anthropic": self._mock_anthropic_module(mock_client)}):
            result = runner.run(_make_context())

        interceptor.intercept.assert_called_once()
        call_arg: ToolCall = interceptor.intercept.call_args[0][0]
        assert call_arg.name == "read_file"
        assert call_arg.id == "tc1"
        assert result.status == "submitted"

    def test_tool_call_rejected_continues(self):
        """When interceptor returns allowed=False, execution continues to next LLM turn."""
        interceptor = _make_interceptor()
        interceptor.intercept = MagicMock(
            return_value=ToolResult(tool_call_id="tc1", output="permission_denied", allowed=False)
        )
        runner = self._make_runner(interceptor=interceptor)

        final_json = json.dumps({"status": "submitted", "summary": "done", "files_changed": []})

        tool_response = self._make_response(
            [self._make_tool_use_block("tc1", "delete_file", {"path": "/etc/passwd"})]
        )
        final_response = self._make_response([self._make_text_block(final_json)])

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [tool_response, final_response]

        import sys
        with patch.dict("sys.modules", {"anthropic": self._mock_anthropic_module(mock_client)}):
            result = runner.run(_make_context())

        interceptor.intercept.assert_called_once()
        assert result.status == "submitted"

    def test_invalid_json_text_returns_failed(self):
        """When anthropic returns non-JSON text, LLMOutput(status=failed) is returned."""
        runner = self._make_runner()

        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_response(
            [self._make_text_block("I cannot complete this task.")]
        )

        import sys
        with patch.dict("sys.modules", {"anthropic": self._mock_anthropic_module(mock_client)}):
            result = runner.run(_make_context())

        assert result.status == "failed"

    def test_sdk_not_installed_returns_failed(self):
        """When anthropic SDK is not installed, LLMOutput(status=failed) is returned."""
        runner = self._make_runner()

        with patch.dict("sys.modules", {"anthropic": None}):
            result = runner.run(_make_context())

        assert result.status == "failed"
        assert "anthropic" in result.raw_text.lower()

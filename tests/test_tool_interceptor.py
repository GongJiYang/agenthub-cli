"""单元测试：ToolInterceptor"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from agenthub.models import SkillConfig, ToolCall, ToolResult
from agenthub.tool_interceptor import ToolInterceptor


# ── 测试夹具 ──────────────────────────────────────────

@pytest.fixture
def skill_config() -> SkillConfig:
    return SkillConfig(
        role="contributor",
        system_prompt_template="",
        tool_whitelist=["read_file", "write_file", "run_tests"],
        path_rules=["src/**", "tests/**"],
        output_schema={},
    )


@pytest.fixture
def trace_writer(tmp_path: Path):
    from agenthub.trace_writer import TraceWriter
    return TraceWriter(trace_path=tmp_path / "trace.jsonl")


def make_interceptor(skill_config, trace_writer, executor=None) -> ToolInterceptor:
    return ToolInterceptor(
        skill_config=skill_config,
        trace_writer=trace_writer,
        executor=executor,
    )


# ── 白名单校验 ────────────────────────────────────────

def test_whitelisted_non_file_tool_allowed(skill_config, trace_writer):
    """白名单内的非文件工具应通过校验，allowed=True。"""
    interceptor = make_interceptor(skill_config, trace_writer)
    tool_call = ToolCall(id="tc1", name="run_tests", args={})
    result = interceptor.intercept(tool_call)
    assert result.allowed is True
    assert result.tool_call_id == "tc1"


def test_non_whitelisted_tool_denied(skill_config, trace_writer):
    """白名单外的工具应返回 permission_denied，allowed=False。"""
    interceptor = make_interceptor(skill_config, trace_writer)
    tool_call = ToolCall(id="tc2", name="delete_file", args={})
    result = interceptor.intercept(tool_call)
    assert result.allowed is False
    assert result.output == "permission_denied"
    assert result.tool_call_id == "tc2"


# ── 路径校验 ──────────────────────────────────────────

def test_file_tool_with_compliant_path_allowed(skill_config, trace_writer):
    """路径合规的 read_file 应通过校验。"""
    interceptor = make_interceptor(skill_config, trace_writer)
    tool_call = ToolCall(id="tc3", name="read_file", args={"path": "src/main.py"})
    result = interceptor.intercept(tool_call)
    assert result.allowed is True


def test_file_tool_with_out_of_bounds_path_denied(skill_config, trace_writer):
    """路径越界的 write_file 应返回 permission_denied。"""
    interceptor = make_interceptor(skill_config, trace_writer)
    tool_call = ToolCall(id="tc4", name="write_file", args={"path": "secrets/config.yaml"})
    result = interceptor.intercept(tool_call)
    assert result.allowed is False
    assert result.output == "permission_denied"


def test_write_file_with_tests_path_allowed(skill_config, trace_writer):
    """tests/ 下的路径应通过 write_file 校验。"""
    interceptor = make_interceptor(skill_config, trace_writer)
    tool_call = ToolCall(id="tc5", name="write_file", args={"path": "tests/test_foo.py"})
    result = interceptor.intercept(tool_call)
    assert result.allowed is True


# ── TraceWriter 记录 ──────────────────────────────────

def test_every_call_is_recorded(skill_config, trace_writer):
    """每次 intercept 调用都应被 TraceWriter 记录。"""
    mock_tw = MagicMock()
    interceptor = make_interceptor(skill_config, mock_tw)

    tc1 = ToolCall(id="a", name="run_tests", args={})
    tc2 = ToolCall(id="b", name="read_file", args={"path": "src/foo.py"})
    tc3 = ToolCall(id="c", name="delete_file", args={})

    r1 = interceptor.intercept(tc1)
    r2 = interceptor.intercept(tc2)
    r3 = interceptor.intercept(tc3)

    assert mock_tw.record.call_count == 3
    mock_tw.record.assert_any_call(tc1, r1)
    mock_tw.record.assert_any_call(tc2, r2)
    mock_tw.record.assert_any_call(tc3, r3)


def test_denied_result_is_also_recorded(skill_config, trace_writer):
    """allowed=False 的结果也应被 TraceWriter 记录。"""
    mock_tw = MagicMock()
    interceptor = make_interceptor(skill_config, mock_tw)

    tool_call = ToolCall(id="d", name="evil_tool", args={})
    result = interceptor.intercept(tool_call)

    assert result.allowed is False
    mock_tw.record.assert_called_once_with(tool_call, result)


# ── executor 注入 ─────────────────────────────────────

def test_executor_called_when_allowed(skill_config, trace_writer):
    """通过校验时应调用 executor，并将其返回值作为 output。"""
    mock_executor = MagicMock(return_value="file_content")
    interceptor = make_interceptor(skill_config, trace_writer, executor=mock_executor)

    tool_call = ToolCall(id="e", name="read_file", args={"path": "src/app.py"})
    result = interceptor.intercept(tool_call)

    mock_executor.assert_called_once_with(tool_call)
    assert result.output == "file_content"
    assert result.allowed is True


def test_executor_not_called_when_denied(skill_config, trace_writer):
    """不通过校验时不应调用 executor。"""
    mock_executor = MagicMock()
    interceptor = make_interceptor(skill_config, trace_writer, executor=mock_executor)

    tool_call = ToolCall(id="f", name="read_file", args={"path": "../etc/passwd"})
    result = interceptor.intercept(tool_call)

    mock_executor.assert_not_called()
    assert result.allowed is False


def test_no_executor_returns_none_output(skill_config, trace_writer):
    """executor 为 None 时，通过校验的工具 output 应为 None。"""
    interceptor = make_interceptor(skill_config, trace_writer, executor=None)
    tool_call = ToolCall(id="g", name="run_tests", args={})
    result = interceptor.intercept(tool_call)
    assert result.allowed is True
    assert result.output is None

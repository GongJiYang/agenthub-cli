"""StreamPrinter 单元测试 + 属性测试。"""
from __future__ import annotations

import io

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agenthub.models import ToolCall
from agenthub.stream_printer import StreamPrinter


# ── 辅助 ──────────────────────────────────────────────

def _make_tool_call(name: str = "read_file", args: dict | None = None) -> ToolCall:
    return ToolCall(id="tc-001", name=name, args=args or {"path": "src/main.py"})


def _printer(show_tools: bool = True) -> tuple[StreamPrinter, io.StringIO]:
    buf = io.StringIO()
    return StreamPrinter(show_tools=show_tools, out=buf), buf


# ── print_token ───────────────────────────────────────

def test_print_token_writes_to_output() -> None:
    p, buf = _printer()
    p.print_token("hello")
    assert buf.getvalue() == "hello"


def test_print_token_multiple() -> None:
    p, buf = _printer()
    for t in ["foo", " ", "bar"]:
        p.print_token(t)
    assert buf.getvalue() == "foo bar"


def test_print_newline() -> None:
    p, buf = _printer()
    p.print_newline()
    assert buf.getvalue() == "\n"


# ── print_tool_call ───────────────────────────────────

def test_print_tool_call_show_tools_true() -> None:
    """show_tools=True 时应打印工具名。"""
    p, buf = _printer(show_tools=True)
    tc = _make_tool_call("read_file", {"path": "src/main.py"})
    p.print_tool_call(tc)
    output = buf.getvalue()
    assert "read_file" in output
    assert "[工具]" in output


def test_print_tool_call_show_tools_false() -> None:
    """show_tools=False 时不应有任何输出。"""
    p, buf = _printer(show_tools=False)
    tc = _make_tool_call("read_file")
    p.print_tool_call(tc)
    assert buf.getvalue() == ""


# ── print_tool_result ─────────────────────────────────

def test_print_tool_result_show_tools_true() -> None:
    """show_tools=True 时应打印结果摘要。"""
    p, buf = _printer(show_tools=True)
    tc = _make_tool_call()
    p.print_tool_result(tc, "file content here")
    assert "file content here" in buf.getvalue()


def test_print_tool_result_truncates_at_200() -> None:
    """结果超过 200 字符时应截断并加省略号。"""
    p, buf = _printer(show_tools=True)
    tc = _make_tool_call()
    long_result = "x" * 300
    p.print_tool_result(tc, long_result)
    output = buf.getvalue()
    assert "..." in output
    assert "x" * 201 not in output


def test_print_tool_result_show_tools_false() -> None:
    """show_tools=False 时不应有任何输出。"""
    p, buf = _printer(show_tools=False)
    tc = _make_tool_call()
    p.print_tool_result(tc, "result")
    assert buf.getvalue() == ""


# ── print_tool_denied ─────────────────────────────────

def test_print_tool_denied_always_prints() -> None:
    """无论 show_tools 值，print_tool_denied 都应打印拒绝信息。"""
    for show in (True, False):
        p, buf = _printer(show_tools=show)
        tc = _make_tool_call("write_file")
        p.print_tool_denied(tc)
        output = buf.getvalue()
        assert "write_file" in output
        assert "permission_denied" in output
        assert "[拒绝]" in output


# ── print_interrupted ─────────────────────────────────

def test_print_interrupted() -> None:
    """print_interrupted 应打印中断提示。"""
    p, buf = _printer()
    p.print_interrupted()
    assert "[已中断]" in buf.getvalue()


# ── print_welcome ─────────────────────────────────────

def test_print_welcome_standalone() -> None:
    p, buf = _printer()
    p.print_welcome("standalone")
    output = buf.getvalue()
    assert "独立对话模式" in output
    assert "/exit" in output


def test_print_welcome_bounty() -> None:
    p, buf = _printer()
    p.print_welcome("bounty", bounty_id="b-123")
    output = buf.getvalue()
    assert "b-123" in output
    assert "/submit" in output


# ── 属性测试 ──────────────────────────────────────────

# 属性 5：流式输出完整性
@given(tokens=st.lists(st.text(min_size=1), min_size=1, max_size=50))
@settings(max_examples=100)
def test_stream_output_completeness(tokens: list[str]) -> None:
    """所有 token 应按顺序出现在输出流中。"""
    p, buf = _printer()
    for t in tokens:
        p.print_token(t)
    p.print_newline()
    output = buf.getvalue()
    assert output.endswith("\n")
    assert output == "".join(tokens) + "\n"


# 属性 6：工具调用可见性控制
@given(
    name=st.sampled_from(["read_file", "write_file", "run_command", "list_directory"]),
    path=st.text(min_size=1, max_size=50),
)
@settings(max_examples=100)
def test_tool_visibility_control(name: str, path: str) -> None:
    """show_tools=True 时输出包含工具名；show_tools=False 时无输出。"""
    tc = ToolCall(id="tc-x", name=name, args={"path": path})

    buf_true = io.StringIO()
    StreamPrinter(show_tools=True, out=buf_true).print_tool_call(tc)
    assert name in buf_true.getvalue()

    buf_false = io.StringIO()
    StreamPrinter(show_tools=False, out=buf_false).print_tool_call(tc)
    assert buf_false.getvalue() == ""

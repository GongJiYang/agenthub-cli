"""ToolExecutor 单元测试 + 属性测试。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agenthub.models import ToolCall
from agenthub.tool_executor import ToolExecutor


# ── 辅助 ──────────────────────────────────────────────

def _make_tool_call(name: str, args: dict) -> ToolCall:
    return ToolCall(id="tc-001", name=name, args=args)


# ── read_file ─────────────────────────────────────────

def test_read_file_success(tmp_path: Path) -> None:
    """read_file 应返回文件内容字符串。"""
    f = tmp_path / "hello.txt"
    f.write_text("hello world", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.read_file(str(f))
    assert result == "hello world"


def test_read_file_not_found() -> None:
    """read_file 文件不存在时应返回错误描述字符串，不抛异常。"""
    executor = ToolExecutor()
    result = executor.read_file("/nonexistent/path/file.txt")
    assert "错误" in result
    assert "不存在" in result


# ── write_file ────────────────────────────────────────

def test_write_file_creates_dirs(tmp_path: Path) -> None:
    """write_file 目标目录不存在时应自动创建。"""
    target = tmp_path / "a" / "b" / "c.txt"
    executor = ToolExecutor()
    result = executor.write_file(str(target), "content")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "content"
    assert "已写入" in result


def test_write_file_overwrites(tmp_path: Path) -> None:
    """write_file 应覆盖已有文件。"""
    f = tmp_path / "file.txt"
    f.write_text("old", encoding="utf-8")
    executor = ToolExecutor()
    executor.write_file(str(f), "new")
    assert f.read_text(encoding="utf-8") == "new"


# ── run_command ───────────────────────────────────────

def test_run_command_success() -> None:
    """run_command 应返回命令输出和退出码 0。"""
    executor = ToolExecutor()
    result = executor.run_command("echo hello")
    assert "hello" in result
    assert "[exit_code: 0]" in result


def test_run_command_nonzero_exit() -> None:
    """run_command 非零退出码时应在结果中包含退出码，不抛异常。"""
    executor = ToolExecutor()
    result = executor.run_command("exit 42", )
    # shell=True 下 exit 42 会返回 42
    assert "[exit_code:" in result


def test_run_command_stderr() -> None:
    """run_command 应捕获 stderr。"""
    executor = ToolExecutor()
    result = executor.run_command("echo err >&2")
    assert "err" in result


def test_run_command_timeout() -> None:
    """run_command 超时应返回超时错误字符串，不抛异常。"""
    executor = ToolExecutor()
    executor.COMMAND_TIMEOUT = 1  # 缩短超时便于测试
    result = executor.run_command("sleep 10")
    assert "超时" in result


# ── list_directory ────────────────────────────────────

def test_list_directory_success(tmp_path: Path) -> None:
    """list_directory 应列出目录下所有直接子项。"""
    (tmp_path / "file1.txt").write_text("a")
    (tmp_path / "file2.txt").write_text("b")
    (tmp_path / "subdir").mkdir()
    executor = ToolExecutor()
    result = executor.list_directory(str(tmp_path))
    assert "file1.txt" in result
    assert "file2.txt" in result
    assert "subdir" in result


def test_list_directory_not_found() -> None:
    """list_directory 目录不存在时应返回错误字符串。"""
    executor = ToolExecutor()
    result = executor.list_directory("/nonexistent/dir")
    assert "错误" in result


def test_list_directory_not_a_dir(tmp_path: Path) -> None:
    """list_directory 路径是文件时应返回错误字符串。"""
    f = tmp_path / "file.txt"
    f.write_text("x")
    executor = ToolExecutor()
    result = executor.list_directory(str(f))
    assert "错误" in result


# ── execute 分发 ──────────────────────────────────────

def test_execute_read_file(tmp_path: Path) -> None:
    """execute 应正确分发 read_file 工具调用。"""
    f = tmp_path / "test.txt"
    f.write_text("data")
    executor = ToolExecutor()
    tc = _make_tool_call("read_file", {"path": str(f)})
    result = executor.execute(tc)
    assert result.allowed is True
    assert result.output == "data"


def test_execute_unknown_tool() -> None:
    """execute 未知工具名时应返回错误描述，不抛异常。"""
    executor = ToolExecutor()
    tc = _make_tool_call("unknown_tool", {})
    result = executor.execute(tc)
    assert result.allowed is True
    assert "未知工具" in str(result.output)


# ── search_code ─────────────────────────────────────────

def test_search_code_finds_match(tmp_path: Path) -> None:
    """search_code 应在文件中找到匹配的行。"""
    f = tmp_path / "hello.py"
    f.write_text("def hello():\n    print('hello world')\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.search_code("hello", str(tmp_path))
    assert "hello" in result
    assert "hello.py" in result


def test_search_code_regex(tmp_path: Path) -> None:
    """search_code 应支持正则表达式搜索。"""
    f = tmp_path / "app.py"
    f.write_text("def foo():\ndef bar():\nclass Baz:\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.search_code(r"def \w+", str(tmp_path))
    assert "foo" in result
    assert "bar" in result


def test_search_code_file_pattern(tmp_path: Path) -> None:
    """search_code 应支持文件名 glob 过滤。"""
    py_file = tmp_path / "code.py"
    py_file.write_text("hello = 1\n", encoding="utf-8")
    js_file = tmp_path / "code.js"
    js_file.write_text("hello = 2\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.search_code("hello", str(tmp_path), "*.py")
    assert "code.py" in result
    assert "code.js" not in result


def test_search_code_no_match(tmp_path: Path) -> None:
    """search_code 无匹配时应返回提示。"""
    f = tmp_path / "empty.py"
    f.write_text("nothing here\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.search_code("nonexistent_pattern_xyz", str(tmp_path))
    assert "未找到" in result


def test_search_code_empty_pattern() -> None:
    """search_code 空 pattern 应返回错误。"""
    executor = ToolExecutor()
    result = executor.search_code("")
    assert "错误" in result


def test_search_code_nonexistent_dir() -> None:
    """search_code 目录不存在时应返回错误。"""
    executor = ToolExecutor()
    result = executor.search_code("test", "/nonexistent/path/xyz")
    assert "错误" in result


def test_search_code_skips_hidden_dirs(tmp_path: Path) -> None:
    """search_code 应跳过隐藏目录。"""
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.py").write_text("match_this\n", encoding="utf-8")
    (tmp_path / "visible.py").write_text("match_this\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.search_code("match_this", str(tmp_path))
    assert "visible.py" in result
    assert "secret.py" not in result


def test_execute_search_code(tmp_path: Path) -> None:
    """execute 应正确分发 search_code 工具调用。"""
    f = tmp_path / "test.py"
    f.write_text("x = 42\n", encoding="utf-8")
    executor = ToolExecutor()
    tc = _make_tool_call("search_code", {"pattern": "42", "path": str(tmp_path)})
    result = executor.execute(tc)
    assert result.allowed is True
    assert "42" in str(result.output)


# ── run_tests ─────────────────────────────────────────────

def test_run_tests_default_command() -> None:
    """run_tests 默认应执行 pytest。"""
    executor = ToolExecutor()
    result = executor.run_tests(command="echo pytest_ok")
    assert "pytest_ok" in result


def test_run_tests_custom_command() -> None:
    """run_tests 应支持自定义测试命令。"""
    executor = ToolExecutor()
    result = executor.run_tests(command="echo custom_test")
    assert "custom_test" in result


def test_run_tests_exit_code() -> None:
    """run_tests 非零退出码时应包含退出码信息。"""
    executor = ToolExecutor()
    result = executor.run_tests(command="exit 1")
    assert "[exit_code: 1]" in result


def test_run_tests_working_dir(tmp_path: Path) -> None:
    """run_tests 应支持指定工作目录。"""
    executor = ToolExecutor()
    result = executor.run_tests(command="pwd", working_dir=str(tmp_path))
    assert str(tmp_path) in result


def test_execute_run_tests() -> None:
    """execute 应正确分发 run_tests 工具调用。"""
    executor = ToolExecutor()
    tc = _make_tool_call("run_tests", {"command": "echo test_pass"})
    result = executor.execute(tc)
    assert result.allowed is True
    assert "test_pass" in str(result.output)


# ── add_comment ───────────────────────────────────────────

def test_add_comment_at_line(tmp_path: Path) -> None:
    """add_comment 应在指定行号后插入注释。"""
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.add_comment(str(f), line=2, message="TODO: fix this")
    assert "添加注释" in result
    content = f.read_text(encoding="utf-8")
    assert "# TODO: fix this" in content


def test_add_comment_at_end(tmp_path: Path) -> None:
    """add_comment 行号为 0 时应在文件末尾追加。"""
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\n", encoding="utf-8")
    executor = ToolExecutor()
    result = executor.add_comment(str(f), line=0, message="end note")
    content = f.read_text(encoding="utf-8")
    assert "# end note" in content


def test_add_comment_js_file(tmp_path: Path) -> None:
    """add_comment 应根据文件扩展名选择注释前缀。"""
    f = tmp_path / "code.js"
    f.write_text("const x = 1;\n", encoding="utf-8")
    executor = ToolExecutor()
    executor.add_comment(str(f), line=1, message="note")
    content = f.read_text(encoding="utf-8")
    assert "// note" in content


def test_add_comment_file_not_found(tmp_path: Path) -> None:
    """add_comment 文件不存在时应返回错误。"""
    executor = ToolExecutor()
    result = executor.add_comment(str(tmp_path / "nope.py"), line=1, message="test")
    assert "错误" in result
    assert "不存在" in result


def test_add_comment_empty_message() -> None:
    """add_comment 空 message 应返回错误。"""
    executor = ToolExecutor()
    result = executor.add_comment("/tmp/x.py", line=1, message="")
    assert "错误" in result


def test_add_comment_empty_file_path() -> None:
    """add_comment 空 file_path 应返回错误。"""
    executor = ToolExecutor()
    result = executor.add_comment("", line=1, message="test")
    assert "错误" in result


def test_execute_add_comment(tmp_path: Path) -> None:
    """execute 应正确分发 add_comment 工具调用。"""
    f = tmp_path / "test.py"
    f.write_text("x = 1\n", encoding="utf-8")
    executor = ToolExecutor()
    tc = _make_tool_call("add_comment", {"file": str(f), "line": 1, "message": "review"})
    result = executor.execute(tc)
    assert result.allowed is True
    assert "添加注释" in str(result.output)


# ── 属性测试 ──────────────────────────────────────────

# 属性 7：文件读写 Round-Trip
@given(content=st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\r")))
@settings(max_examples=100)
def test_file_read_write_round_trip(content: str) -> None:
    """对于任意字符串内容（不含裸 CR），write_file 后 read_file 应返回相同内容。"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "roundtrip.txt")
        executor = ToolExecutor()
        executor.write_file(path, content)
        result = executor.read_file(path)
        assert result == content


# 属性 8：目录列表完整性
@given(names=st.lists(
    st.text(min_size=1, max_size=20,
            alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_-")),
    min_size=1, max_size=10, unique=True,
))
@settings(max_examples=50)
def test_list_directory_completeness(names: list[str]) -> None:
    """list_directory 结果应包含目录下所有直接子项名称。"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            Path(os.path.join(tmp, name)).write_text("x")
        executor = ToolExecutor()
        result = executor.list_directory(tmp)
        for name in names:
            assert name in result


# 属性 10：非零退出码命令结果包含退出码信息
@given(code=st.integers(min_value=1, max_value=125))
@settings(max_examples=30)
def test_nonzero_exit_code_in_result(code: int) -> None:
    """非零退出码的命令，run_command 结果应包含该退出码数值，不抛异常。"""
    executor = ToolExecutor()
    result = executor.run_command(f"exit {code}")
    assert f"[exit_code: {code}]" in result

"""单元测试：TraceWriter"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenthub.models import ToolCall, ToolResult
from agenthub.trace_writer import TraceWriter


def _make_call(call_id: str, name: str = "read_file") -> ToolCall:
    return ToolCall(id=call_id, name=name, args={"path": f"/tmp/{call_id}"})


def _make_result(call_id: str, allowed: bool = True) -> ToolResult:
    return ToolResult(tool_call_id=call_id, output="ok", allowed=allowed)


# ── 基础功能 ──────────────────────────────────────────────────────────

def test_record_then_to_trace_commit_entry_count(tmp_path):
    """record 后 to_trace_commit 的 entries 数量正确。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    for i in range(5):
        tw.record(_make_call(f"id-{i}"), _make_result(f"id-{i}"))
    commit = tw.to_trace_commit(bounty_id="b1", role="contributor")
    assert len(commit.entries) == 5


def test_entries_order_matches_record_order(tmp_path):
    """entries 顺序与 record 调用顺序一致。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    ids = ["first", "second", "third"]
    for cid in ids:
        tw.record(_make_call(cid), _make_result(cid))
    commit = tw.to_trace_commit(bounty_id="b1", role="contributor")
    assert [e.tool_call.id for e in commit.entries] == ids


def test_tool_call_id_preserved_in_entries(tmp_path):
    """tool_call.id 在 entries 中正确保留。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    tw.record(_make_call("unique-xyz"), _make_result("unique-xyz"))
    commit = tw.to_trace_commit(bounty_id="b1", role="tester")
    assert commit.entries[0].tool_call.id == "unique-xyz"


def test_denied_result_is_recorded(tmp_path):
    """allowed=False 的 ToolResult 也被正确记录。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    tw.record(_make_call("denied-1"), _make_result("denied-1", allowed=False))
    commit = tw.to_trace_commit(bounty_id="b1", role="contributor")
    assert len(commit.entries) == 1
    assert commit.entries[0].result.allowed is False


def test_clear_empties_entries(tmp_path):
    """clear 后 entries 为空。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    tw.record(_make_call("c1"), _make_result("c1"))
    tw.clear()
    commit = tw.to_trace_commit(bounty_id="b1", role="contributor")
    assert commit.entries == []


# ── trace.jsonl 文件写入 ──────────────────────────────────────────────

def test_trace_jsonl_written_correctly(tmp_path):
    """trace.jsonl 文件被正确写入，每行是合法 JSON 且包含正确字段。"""
    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path=trace_path)
    tw.record(_make_call("file-id-1"), _make_result("file-id-1"))
    tw.record(_make_call("file-id-2"), _make_result("file-id-2", allowed=False))

    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["tool_call"]["id"] == "file-id-1"
    assert first["result"]["allowed"] is True
    assert "timestamp" in first

    second = json.loads(lines[1])
    assert second["tool_call"]["id"] == "file-id-2"
    assert second["result"]["allowed"] is False


def test_clear_truncates_trace_jsonl(tmp_path):
    """clear 后 trace.jsonl 文件内容为空。"""
    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path=trace_path)
    tw.record(_make_call("x1"), _make_result("x1"))
    tw.clear()
    assert trace_path.read_text(encoding="utf-8") == ""


def test_trace_jsonl_parent_dir_created_automatically(tmp_path):
    """trace.jsonl 的父目录不存在时自动创建。"""
    trace_path = tmp_path / "nested" / "dir" / "trace.jsonl"
    tw = TraceWriter(trace_path=trace_path)
    tw.record(_make_call("auto-dir"), _make_result("auto-dir"))
    assert trace_path.exists()


def test_to_trace_commit_bounty_id_and_role(tmp_path):
    """to_trace_commit 正确设置 bounty_id 和 role。"""
    tw = TraceWriter(trace_path=tmp_path / "trace.jsonl")
    commit = tw.to_trace_commit(bounty_id="bounty-42", role="reviewer")
    assert commit.bounty_id == "bounty-42"
    assert commit.role == "reviewer"

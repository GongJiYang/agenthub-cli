from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ToolCall, ToolResult, TraceEntry, TraceCommit


def _to_dict(obj) -> object:
    """递归将 dataclass 转为可 JSON 序列化的 dict。"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


class TraceWriter:
    DEFAULT_TRACE_PATH = Path("~/.agenthub/trace.jsonl").expanduser()

    def __init__(self, trace_path: Path | None = None) -> None:
        self._trace_path: Path = trace_path or self.DEFAULT_TRACE_PATH
        self._entries: list[TraceEntry] = []

    # ------------------------------------------------------------------
    def record(self, tool_call: ToolCall, result: ToolResult) -> None:
        """追加一条 TraceEntry，并将其以 JSON 格式追加写入 trace.jsonl。"""
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = TraceEntry(tool_call=tool_call, result=result, timestamp=timestamp)
        self._entries.append(entry)

        self._trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self._trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_to_dict(entry), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    def to_trace_commit(self, bounty_id: str, role: str) -> TraceCommit:
        """将内存中所有记录序列化为 TraceCommit 对象。"""
        return TraceCommit(
            bounty_id=bounty_id,
            role=role,
            entries=list(self._entries),
        )

    # ------------------------------------------------------------------
    def clear(self) -> None:
        """清空内存记录，并清空 trace.jsonl 文件（用于新任务开始时）。"""
        self._entries.clear()
        if self._trace_path.exists():
            self._trace_path.write_text("", encoding="utf-8")

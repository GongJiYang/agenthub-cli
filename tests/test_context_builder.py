"""
Tests for ContextBuilder (tasks 10.1 & 10.2).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agenthub.context_builder import ContextBuilder
from agenthub.models import BountyDetail, SkillConfig


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_bounty(files_to_read: list[str], token_budget: int = 1000) -> BountyDetail:
    return BountyDetail(
        id="b-001",
        role="contributor",
        title="Test Bounty",
        description="Fix the bug",
        files_to_read=files_to_read,
        token_budget=token_budget,
        status="open",
        repo_name="test-repo",
    )


def _make_skill(template: str = "You are an agent. Task: {{ bounty.description }}") -> SkillConfig:
    return SkillConfig(
        role="contributor",
        system_prompt_template=template,
        tool_whitelist=["read_file"],
        path_rules=["src/**"],
        output_schema={},
    )


def _make_client(bounty: BountyDetail) -> MagicMock:
    client = MagicMock()
    client.get_bounty.return_value = bounty
    return client


# ── unit tests ────────────────────────────────────────────────────────────────

class TestContextBuilderNormal:
    def test_files_count_equals_files_to_read(self, tmp_path: Path) -> None:
        """files 数量等于 files_to_read 长度。"""
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("print('a')")
        f2.write_text("print('b')")

        bounty = _make_bounty([str(f1), str(f2)])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert len(ctx.files) == len(bounty.files_to_read)

    def test_existing_file_content_is_read(self, tmp_path: Path) -> None:
        """存在的文件内容被正确读取，missing=False。"""
        f = tmp_path / "hello.txt"
        f.write_text("hello world")

        bounty = _make_bounty([str(f)])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        fc = ctx.files[0]
        assert fc.content == "hello world"
        assert fc.missing is False

    def test_missing_file_has_missing_true(self, tmp_path: Path) -> None:
        """不存在的文件 FileContent.missing=True，content=None。"""
        missing_path = str(tmp_path / "nonexistent.py")

        bounty = _make_bounty([missing_path])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        fc = ctx.files[0]
        assert fc.missing is True
        assert fc.content is None

    def test_system_prompt_is_not_empty(self, tmp_path: Path) -> None:
        """system_prompt 非空。"""
        bounty = _make_bounty([])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert ctx.system_prompt != ""

    def test_system_prompt_renders_bounty_description(self, tmp_path: Path) -> None:
        """system_prompt 包含 bounty.description 渲染结果。"""
        bounty = _make_bounty([])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert bounty.description in ctx.system_prompt

    def test_bounty_field_equals_get_bounty_return(self) -> None:
        """ctx.bounty 等于 client.get_bounty 的返回值。"""
        bounty = _make_bounty([])
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert ctx.bounty is bounty

    def test_token_budget_set_from_bounty(self) -> None:
        """ctx.token_budget 等于 bounty.token_budget。"""
        bounty = _make_bounty([], token_budget=512)
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert ctx.token_budget == 512


class TestContextBuilderTokenTruncation:
    def test_no_truncation_within_budget(self, tmp_path: Path) -> None:
        """未超出预算时内容不被截断。"""
        f = tmp_path / "small.py"
        content = "x" * 100  # 100 chars → 25 tokens
        f.write_text(content)

        bounty = _make_bounty([str(f)], token_budget=100)  # budget = 400 chars
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        assert ctx.files[0].content == content

    def test_truncation_when_over_budget(self, tmp_path: Path) -> None:
        """超出预算时总字符数 ≤ token_budget * 4。"""
        f1 = tmp_path / "big1.py"
        f2 = tmp_path / "big2.py"
        f1.write_text("a" * 500)
        f2.write_text("b" * 500)

        token_budget = 100  # budget = 400 chars; total = 1000 chars → must truncate
        bounty = _make_bounty([str(f1), str(f2)], token_budget=token_budget)
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        total = sum(len(fc.content) for fc in ctx.files if fc.content is not None)
        assert total <= token_budget * 4

    def test_truncation_removes_from_last_file_first(self, tmp_path: Path) -> None:
        """截断从最后一个文件开始。"""
        f1 = tmp_path / "first.py"
        f2 = tmp_path / "last.py"
        f1.write_text("a" * 200)
        f2.write_text("b" * 200)

        # budget = 300 chars; total = 400 → need to cut 100 from last file
        token_budget = 75  # 75 * 4 = 300
        bounty = _make_bounty([str(f1), str(f2)], token_budget=token_budget)
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        # first file should be untouched
        assert ctx.files[0].content == "a" * 200
        # last file should be truncated
        assert len(ctx.files[1].content) < 200

    def test_truncation_with_missing_files(self, tmp_path: Path) -> None:
        """截断逻辑跳过 missing 文件（content=None）。"""
        f_existing = tmp_path / "real.py"
        f_existing.write_text("c" * 500)
        missing_path = str(tmp_path / "ghost.py")

        token_budget = 50  # 50 * 4 = 200 chars
        bounty = _make_bounty([str(f_existing), missing_path], token_budget=token_budget)
        client = _make_client(bounty)
        ctx = ContextBuilder(client).build("b-001", _make_skill())

        total = sum(len(fc.content) for fc in ctx.files if fc.content is not None)
        assert total <= token_budget * 4
        # missing file stays missing
        assert ctx.files[1].missing is True
        assert ctx.files[1].content is None

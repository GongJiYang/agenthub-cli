"""workspace 模块单元测试。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agenthub.workspace import get_workspace_root, clone_repo, prepare_workspace, WORKSPACE_BASE


def test_get_workspace_root_custom() -> None:
    """指定 config_root 时应返回自定义路径。"""
    result = get_workspace_root("bounty-123", config_root="/tmp/my-workspace")
    assert result == Path("/tmp/my-workspace")


def test_get_workspace_root_default() -> None:
    """未指定 config_root 时应返回 WORKSPACE_BASE / bounty_id。"""
    result = get_workspace_root("bounty-123")
    assert result == WORKSPACE_BASE / "bounty-123"


def test_clone_repo_success(tmp_path: Path) -> None:
    """clone_repo 应成功克隆到指定目录。"""
    src = tmp_path / "source"
    src.mkdir()
    (src / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(src), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(src), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(src), capture_output=True, check=True)

    dest = tmp_path / "cloned"
    result = clone_repo(str(src), dest)
    assert result == dest
    assert (dest / "README.md").exists()


def test_clone_repo_existing_git(tmp_path: Path) -> None:
    """clone_repo 目标目录已存在 .git 时应直接返回。"""
    dest = tmp_path / "existing"
    dest.mkdir()
    (dest / ".git").mkdir()
    result = clone_repo("https://example.com/repo.git", dest)
    assert result == dest


def test_clone_repo_failure() -> None:
    """clone_repo 克隆失败时应抛出 RuntimeError。"""
    with pytest.raises(RuntimeError, match="git clone 失败"):
        clone_repo("https://nonexistent.invalid/repo.git", Path("/tmp/test_clone_fail_xyz"))


def test_prepare_workspace_with_repo(tmp_path: Path) -> None:
    """prepare_workspace 有 repo_url 时应克隆仓库。"""
    src = tmp_path / "source"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(src), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(src), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(src), capture_output=True, check=True)

    dest = tmp_path / "workspace"
    result = prepare_workspace("test-bounty", repo_url=str(src), config_root=str(dest))
    assert result == dest
    assert (dest / "file.txt").exists()


def test_prepare_workspace_no_repo(tmp_path: Path) -> None:
    """prepare_workspace 无 repo_url 时应创建空目录。"""
    dest = tmp_path / "workspace"
    result = prepare_workspace("test-bounty", config_root=str(dest))
    assert result == dest
    assert dest.exists()


def test_prepare_workspace_default_path() -> None:
    """prepare_workspace 无 config_root 时应使用默认路径。"""
    result = prepare_workspace("test-bounty")
    assert result == WORKSPACE_BASE / "test-bounty"
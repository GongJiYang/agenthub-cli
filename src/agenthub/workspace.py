"""工作区管理：克隆仓库、管理工作目录。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

WORKSPACE_BASE = Path("~/.agenthub/workspaces").expanduser()


def get_workspace_root(bounty_id: str, config_root: str = "") -> Path:
    """根据 bounty_id 返回工作区根目录。

    优先级：
    1. config_root（来自 AppConfig.workspace_root）
    2. WORKSPACE_BASE / bounty_id
    """
    if config_root:
        return Path(config_root)
    return WORKSPACE_BASE / bounty_id


def clone_repo(repo_url: str, dest: Path, branch: str | None = None) -> Path:
    """克隆仓库到指定目录，返回实际工作目录。

    Args:
        repo_url: Git 仓库 URL（HTTPS 或 SSH）。
        dest: 目标目录路径。
        branch: 可选的分支名，默认为仓库默认分支。

    Returns:
        克隆后的仓库根目录 Path。

    Raises:
        RuntimeError: 克隆失败时抛出。
    """
    dest = Path(dest)
    if dest.exists() and (dest / ".git").exists():
        return dest

    cmd = ["git", "clone"]
    if branch:
        cmd.extend(["--branch", branch, "--single-branch"])
    cmd.extend([repo_url, str(dest)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone 失败：{result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git clone 超时（>120秒）：{repo_url}")

    return dest


def prepare_workspace(
    bounty_id: str,
    repo_url: str | None = None,
    branch: str | None = None,
    config_root: str = "",
) -> Path:
    """准备任务执行的工作区。

    如果提供了 repo_url，则克隆仓库；否则仅确保目录存在。

    Args:
        bounty_id: 任务 ID，用于生成工作区目录名。
        repo_url: 可选的 Git 仓库 URL。
        branch: 可选的分支名。
        config_root: 可选的工作区根目录覆盖（来自 AppConfig）。

    Returns:
        工作区根目录 Path。
    """
    workspace = get_workspace_root(bounty_id, config_root)

    if repo_url:
        workspace = clone_repo(repo_url, workspace, branch)
    else:
        workspace.mkdir(parents=True, exist_ok=True)

    return workspace
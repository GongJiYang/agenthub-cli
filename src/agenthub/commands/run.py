"""run 命令：读取 lock.json 并执行完整的 Bounty 处理流程。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..auth import AuthModule
from ..config import load_config
from ..context_builder import ContextBuilder
from ..http_client import AgentHubClient
from ..process_manager import ProcessManager
from ..schema_validator import SchemaValidator
from ..skill_loader import SkillLoader
from ..workspace import prepare_workspace

LOCK_PATH = Path("~/.agenthub/lock.json").expanduser()


@click.command("run")
def run_command() -> None:
    """执行当前认领的 Bounty 任务。"""
    if not LOCK_PATH.exists():
        click.echo("❌ 未找到活跃任务，请先执行 agenthub claim <bounty_id>", err=True)
        sys.exit(1)

    try:
        lock_data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        bounty_id = lock_data["bounty_id"]
    except (json.JSONDecodeError, KeyError) as e:
        click.echo(f"❌ lock.json 格式错误：{e}", err=True)
        sys.exit(1)

    click.echo(f"🚀 开始执行 Bounty {bounty_id}")

    app_config = load_config()
    auth = AuthModule()
    client = AgentHubClient(base_url=app_config.api_base_url, auth=auth)

    # 准备工作区（如果 bounty 有 repo_url 则克隆仓库）
    repo_url = lock_data.get("repo_url")
    branch = lock_data.get("branch")
    workspace = prepare_workspace(
        bounty_id=bounty_id,
        repo_url=repo_url,
        branch=branch,
        config_root=app_config.workspace_root,
    )
    click.echo(f"📂 工作区：{workspace}")

    skill_loader = SkillLoader()
    context_builder = ContextBuilder(client=client, workspace_root=str(workspace))
    schema_validator = SchemaValidator()

    pm = ProcessManager(
        client=client,
        auth=auth,
        skill_loader=skill_loader,
        context_builder=context_builder,
        schema_validator=schema_validator,
        bounty_id=bounty_id,
        workspace_root=str(workspace),
    )

    exit_code = pm.run()
    if exit_code == 0:
        click.echo(f"🎉 Bounty {bounty_id} 执行完成")
    else:
        click.echo(f"💥 Bounty {bounty_id} 执行失败", err=True)
    sys.exit(exit_code)

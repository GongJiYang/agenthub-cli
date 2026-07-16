"""status 命令：查看当前活跃任务的状态。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..auth import AuthModule, AuthenticationError
from ..config import load_config
from ..http_client import AgentHubClient, APIError

LOCK_PATH = Path("~/.agenthub/lock.json").expanduser()


@click.command("status")
def status_command() -> None:
    """查看当前认领任务的状态。"""
    if not LOCK_PATH.exists():
        click.echo("无活跃任务")
        sys.exit(0)

    try:
        lock_data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        bounty_id = lock_data["bounty_id"]
    except (json.JSONDecodeError, KeyError) as e:
        click.echo(f"lock.json 格式错误：{e}", err=True)
        sys.exit(1)

    try:
        app_config = load_config()
        auth = AuthModule()
        client = AgentHubClient(base_url=app_config.api_base_url, auth=auth)
        bounty = client.get_bounty(bounty_id)

        click.echo(f"任务 ID：{bounty.id}")
        click.echo(f"标题：{bounty.title}")
        click.echo(f"状态：{bounty.status}")
        click.echo(f"角色：{bounty.role}")
        click.echo(f"剩余 Token 预算：{bounty.token_budget}")
    except AuthenticationError:
        click.echo("请先登录以查看任务状态：agenthub login")
    except APIError as e:
        click.echo(f"获取任务状态失败：{e}", err=True)
        sys.exit(1)

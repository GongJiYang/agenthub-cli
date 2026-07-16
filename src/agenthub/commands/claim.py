"""claim 命令：认领指定 Bounty 并保存 BountyLock。"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import click
from rich.console import Console

from ..auth import AuthModule, AuthenticationError
from ..config import load_config
from ..http_client import AgentHubClient, APIError, BountyLockedError
from .book import render_spec

LOCK_PATH = Path("~/.agenthub/lock.json").expanduser()
AGENT_INFO_PATH = Path("~/.agenthub/agent.json").expanduser()


def _load_agent_id() -> str:
    if not AGENT_INFO_PATH.exists():
        click.echo("未找到 Agent 信息，请先执行 agenthub login", err=True)
        sys.exit(1)
    data = json.loads(AGENT_INFO_PATH.read_text(encoding="utf-8"))
    return data["agent_id"]


@click.command("claim")
@click.argument("bounty_id")
def claim_command(bounty_id: str) -> None:
    """认领 Bounty 任务并保存任务锁。"""
    try:
        agent_id = _load_agent_id()
        app_config = load_config()
        auth = AuthModule()
        client = AgentHubClient(base_url=app_config.api_base_url, auth=auth)

        # 获取任务规格并展示，要求用户确认后再认领
        console = Console()
        try:
            bounty = client.get_bounty_raw(bounty_id)
        except APIError as e:
            console.print(f"[red]❌ 获取任务失败：{e}[/red]", err=True)
            sys.exit(1)

        spec = bounty.get("spec")
        status = bounty.get("status", "")
        render_spec(spec, console, bounty_id=str(bounty.get("id", bounty_id)), status=status)

        click.confirm("确认认领此任务？", abort=True)

        lock = client.claim_bounty(bounty_id, agent_id=agent_id)

        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.write_text(
            json.dumps(dataclasses.asdict(lock), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        click.echo(f"任务认领成功：{bounty_id}")
    except BountyLockedError as e:
        click.echo(f"任务已被占用：{e}", err=True)
        sys.exit(1)
    except AuthenticationError as e:
        click.echo(f"认证失败：{e}\n请执行 agenthub login", err=True)
        sys.exit(1)

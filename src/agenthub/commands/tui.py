from __future__ import annotations

from typing import Optional

import click

from ..auth import AuthModule, AuthenticationError
from ..config import load_config


@click.command("tui")
@click.option("--bounty", "bounty_id", default=None, help="关联的 Bounty ID")
@click.option("--model", default=None, help="使用的模型名称")
@click.option("--agent-id", default=None, help="Agent ID（默认从 ~/.agenthub/agent.json 读取）")
@click.option("--role", default=None, help="角色过滤（architect/contributor/executor/reviewer/tester）")
def tui_command(bounty_id: Optional[str], model: Optional[str], agent_id: Optional[str], role: Optional[str]) -> None:
    """启动 TUI 仪表盘。"""
    try:
        from ..tui.app import AgentHubTUI
    except ImportError:
        click.echo("错误：textual 未安装，请执行：pip install textual", err=True)
        raise SystemExit(1)

    config = load_config()
    auth = AuthModule()

    if not agent_id:
        import json
        from pathlib import Path
        agent_info_path = Path("~/.agenthub/agent.json").expanduser()
        if agent_info_path.exists():
            data = json.loads(agent_info_path.read_text(encoding="utf-8"))
            agent_id = data.get("agent_id")

    app = AgentHubTUI(
        api_base_url=config.api_base_url,
        agent_id=agent_id,
        role=role,
    )
    app.run()
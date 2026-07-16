"""chat 命令：启动交互式对话模式。"""
from __future__ import annotations

import sys

import click

from ..auth import AuthModule, AuthenticationError
from ..chat_runner import ChatRunner
from ..config import load_config


@click.command("chat")
@click.option("--bounty", "bounty_id", default=None, help="关联的 Bounty ID")
@click.option("--model", default=None, help="使用的模型名称（默认从配置文件读取）")
@click.option(
    "--show-tools/--no-show-tools",
    default=True,
    help="是否在终端显示工具调用详情（默认开启）",
)
@click.option("--save-history", "save_path", default=None, help="对话历史保存路径")
def chat_command(
    bounty_id: str | None,
    model: str | None,
    show_tools: bool,
    save_path: str | None,
) -> None:
    """启动交互式对话模式（类似 Claude Code / Cursor）。"""
    config = load_config()
    auth = AuthModule()

    # Bounty 模式需要认证
    if bounty_id:
        try:
            auth.load_token()
        except AuthenticationError:
            click.echo("认证失败：请先执行 agenthub login", err=True)
            sys.exit(1)

    runner = ChatRunner(
        config=config,
        auth=auth,
        bounty_id=bounty_id,
        model=model or config.llm.model,
        show_tools=show_tools,
        save_path=save_path,
    )
    sys.exit(runner.run())

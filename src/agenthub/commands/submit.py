"""submit 命令：提交已集成在 run 中，此命令提供说明。"""

from __future__ import annotations

import click


@click.command("submit")
def submit_command() -> None:
    """提交 Bounty 任务结果（已集成在 run 中）。"""
    click.echo("提交已集成在 agenthub run 中，执行完成后自动提交。")

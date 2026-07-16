"""AgentHub CLI 入口：注册所有子命令。"""

import click

from .commands.login import login_command
from .commands.claim import claim_command
from .commands.run import run_command
from .commands.submit import submit_command
from .commands.status import status_command
from .commands.chat import chat_command
from .commands.tui import tui_command
from .commands.architect import architect_group, task_group


@click.group()
def cli() -> None:
    """AgentHub CLI — AI Agent 任务执行工具"""
    pass


cli.add_command(login_command, name="login")
cli.add_command(claim_command, name="claim")
cli.add_command(run_command, name="run")
cli.add_command(submit_command, name="submit")
cli.add_command(status_command, name="status")
cli.add_command(chat_command, name="chat")
cli.add_command(tui_command, name="tui")
cli.add_command(architect_group, name="architect")
cli.add_command(task_group, name="task")

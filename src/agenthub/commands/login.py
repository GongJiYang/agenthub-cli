"""login 命令：先用户认证，再注册 Agent。"""

from __future__ import annotations

import sys

import click

from ..auth import AuthModule, AuthenticationError
from ..config import load_config
from ..http_client import AgentHubClient, APIError

VALID_ROLES = ["architect", "contributor", "executor", "reviewer", "tester", "librarian"]


@click.command("login")
def login_command() -> None:
    """用户登录并注册 Agent。"""
    app_config = load_config()
    auth = AuthModule()
    client = AgentHubClient(base_url=app_config.api_base_url, auth=auth)

    # 步骤 1：提示用户输入 email 和 password
    email = click.prompt("邮箱")
    password = click.prompt("密码", hide_input=True)

    # 步骤 2：尝试登录，失败则询问是否注册
    token: str
    try:
        result = client.login_user(email, password)
        token = result["access_token"]
        click.echo("登录成功。")
    except AuthenticationError:
        register = click.confirm("该邮箱未注册，是否注册新账号？", default=False)
        if not register:
            click.echo("已取消。", err=True)
            sys.exit(1)
        try:
            result = client.register_user(email, password)
            token = result["access_token"]
            click.echo("注册成功。")
        except APIError as e:
            click.echo(f"注册失败：{e}", err=True)
            sys.exit(1)

    # 步骤 3：提示用户输入 agent 信息
    name = click.prompt("Agent 名称")

    # 角色选择：显示编号列表
    role_descriptions = {
        "architect":   "架构师 — 设计系统、分解任务、治理决策",
        "contributor": "贡献者 — 编写代码、实现功能",
        "executor":    "执行者 — 运行测试、验证代码",
        "reviewer":    "审查者 — 审查代码、批准/拒绝",
        "tester":      "测试者 — 黑盒测试、安全测试",
        "librarian":   "图书管理员 — 知识管理、文档维护",
    }
    click.echo("\n请选择角色：")
    for i, r in enumerate(VALID_ROLES, 1):
        click.echo(f"  {i}. {r:12s}  {role_descriptions[r]}")
    while True:
        choice = click.prompt("\n输入编号", default="2")
        if choice.isdigit() and 1 <= int(choice) <= len(VALID_ROLES):
            role = VALID_ROLES[int(choice) - 1]
            break
        click.echo(f"请输入 1-{len(VALID_ROLES)} 之间的数字", err=True)

    model = click.prompt("模型名称", default="claude-opus-4-5")

    # 步骤 4：用 JWT 注册 agent
    try:
        agent_result = client.register_agent(name=name, model_name=model, role=role, jwt_token=token)
    except APIError as e:
        click.echo(f"Agent 注册失败：{e}", err=True)
        sys.exit(1)

    api_key = agent_result["api_key"]
    agent_id = agent_result["id"]

    # 步骤 5：保存凭证
    auth.save_token(token)
    auth.save_agent_key(api_key)
    auth.save_agent_info(agent_id=agent_id, name=name, role=role)

    # 步骤 6：打印成功信息
    click.echo(f"\n登录成功！")
    click.echo(f"Agent ID : {agent_id}")
    click.echo(f"角色     : {role}")
    click.echo(f"JWT 已保存到 ~/.agenthub/token")
    click.echo(f"API Key 已保存到 ~/.agenthub/agent_key")



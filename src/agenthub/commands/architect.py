"""architect 命令组：架构师专用命令（创建任务、分解任务、管理仓库）。"""

from __future__ import annotations

import json
import sys
from typing import Optional

import click
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..auth import AuthModule, AuthenticationError
from ..config import load_config
from ..http_client import AgentHubClient, APIError
from .book import book_group, render_spec

VALID_ROLES = ["architect", "contributor", "executor", "reviewer", "tester", "librarian"]

ROLE_LABELS = {
    "architect":   "架构师",
    "contributor": "贡献者",
    "executor":    "执行者",
    "reviewer":    "审查者",
    "tester":      "测试者",
    "librarian":   "图书管理员",
}


def _make_client() -> tuple[AgentHubClient, AuthModule]:
    config = load_config()
    auth = AuthModule()
    return AgentHubClient(base_url=config.api_base_url, auth=auth), auth


def _get_architect_prompt(client: AgentHubClient) -> str:
    """从后端拉取架构师 system prompt。"""
    try:
        resp = client._client.get("/roles/architect/prompt")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("prompt") or data.get("content") or ""
    except Exception:
        pass
    # fallback：读本地 skills/architect.yaml
    try:
        import yaml
        from pathlib import Path
        skill_path = Path(__file__).parent.parent.parent.parent / "skills" / "architect.yaml"
        if skill_path.exists():
            with open(skill_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("system_prompt_template", "")
    except Exception:
        pass
    return ""


def _call_ai_design(system_prompt: str, user_requirement: str, api_key: str, model: str, feedback: str = "") -> str:
    """调用 Anthropic API，返回 AI 生成的任务树 JSON 字符串。"""
    try:
        import anthropic
    except ImportError:
        click.echo("❌ 需要安装 anthropic SDK：pip install anthropic", err=True)
        sys.exit(1)

    messages = [{"role": "user", "content": user_requirement}]
    if feedback:
        messages.append({"role": "assistant", "content": "（上一版方案）"})
        messages.append({"role": "user", "content": f"请根据以下反馈修改方案：\n{feedback}"})

    client = anthropic.Anthropic(api_key=api_key)
    click.echo("🤖 AI 正在设计任务树...", err=True)
    full_text = ""
    with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system_prompt + "\n\n请直接输出符合上述格式的 JSON，不要有任何 markdown 包裹或额外说明。",
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_text += text
    print()  # 换行
    return full_text


def _extract_json(text: str) -> dict | None:
    """从 AI 输出中提取 JSON 对象。"""
    # 去掉 markdown 代码块
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
    return None


def _flatten_tree(node: dict, depth: int = 0) -> list[tuple[int, dict]]:
    """将任务树展平为 (depth, node) 列表，便于展示。"""
    result = [(depth, node)]
    for child in node.get("children", []):
        result.extend(_flatten_tree(child, depth + 1))
    return result


def _print_task_tree(root_task: dict) -> None:
    """打印任务树，带缩进和角色颜色。"""
    ROLE_COLORS = {
        "architect":   "\033[35m",   # 紫
        "contributor": "\033[34m",   # 蓝
        "executor":    "\033[33m",   # 黄
        "reviewer":    "\033[32m",   # 绿
        "tester":      "\033[31m",   # 红
        "librarian":   "\033[36m",   # 青
    }
    RESET = "\033[0m"

    flat = _flatten_tree(root_task)
    click.echo()
    for i, (depth, node) in enumerate(flat):
        indent = "  " * depth
        prefix = "└─ " if depth > 0 else "📋 "
        role = node.get("required_role", "contributor")
        color = ROLE_COLORS.get(role, "")
        track = f" [{node['track']}]" if node.get("track") else ""
        hours = f" ~{node['estimated_hours']}h" if node.get("estimated_hours") else ""
        deps = node.get("dependencies", [])
        dep_str = f" (依赖: {', '.join(deps)})" if deps else ""
        click.echo(
            f"  {i:>2}. {indent}{prefix}"
            f"{color}{node.get('title','')}{RESET}"
            f"  {color}[{role}]{RESET}{track}{hours}{dep_str}"
        )
        if node.get("description"):
            click.echo(f"      {indent}    {node['description'][:80]}")
    click.echo()


def _review_loop(root_task: dict, repo_name: str, api_key: str, model: str,
                 system_prompt: str, user_requirement: str) -> dict | None:
    """
    用户审查任务树，支持：
    - 确认提交
    - 打回某条任务让 AI 重新生成
    - 整体重新生成
    - 放弃
    返回最终确认的 root_task，或 None 表示放弃。
    """
    current_root = root_task

    while True:
        _print_task_tree(current_root)
        flat = _flatten_tree(current_root)

        click.echo("操作选项：")
        click.echo("  [y] 确认，提交到平台")
        click.echo("  [r] 整体重新生成")
        click.echo("  [编号] 打回某条任务，输入反馈让 AI 修改")
        click.echo("  [q] 放弃")
        choice = click.prompt("\n请选择", default="y").strip().lower()

        if choice == "y":
            # 为每个叶节点收集验收标准
            flat = _flatten_tree(current_root)
            for _, node in flat:
                if not node.get("children", []):
                    title = node.get("title", "")
                    click.echo(f"\n请为任务 '{title}' 输入验收标准（每行一条，空行结束）：")
                    criteria_list = []
                    while True:
                        line = input()
                        if not line:
                            break
                        criteria_list.append(line)
                    node["acceptance_criteria"] = criteria_list
            return current_root

        elif choice == "q":
            click.echo("已放弃")
            return None

        elif choice == "r":
            feedback = click.prompt("整体修改意见（可选，直接回车跳过）", default="")
            raw = _call_ai_design(system_prompt, user_requirement, api_key, model, feedback or "请重新设计")
            new_data = _extract_json(raw)
            if not new_data:
                click.echo("❌ AI 输出无法解析为 JSON，请重试", err=True)
                continue
            current_root = new_data.get("root_task", new_data)

        elif choice.isdigit() and 0 <= int(choice) < len(flat):
            idx = int(choice)
            _, target_node = flat[idx]
            click.echo(f"\n打回任务：{target_node.get('title')}")
            feedback = click.prompt("请输入修改意见")

            # 构造针对该节点的修改请求
            node_json = json.dumps(target_node, ensure_ascii=False, indent=2)
            patch_prompt = (
                f"以下是当前任务树中的一个节点：\n{node_json}\n\n"
                f"用户反馈：{feedback}\n\n"
                f"请修改这个节点（及其子节点），返回修改后的完整节点 JSON，格式与原来相同。"
            )
            raw = _call_ai_design(system_prompt, patch_prompt, api_key, model)
            new_node = _extract_json(raw)
            if not new_node:
                click.echo("❌ AI 输出无法解析，请重试", err=True)
                continue

            # 替换树中对应节点
            def replace_node(node: dict, old_title: str, new_node: dict) -> dict:
                if node.get("title") == old_title:
                    return new_node
                node["children"] = [
                    replace_node(c, old_title, new_node)
                    for c in node.get("children", [])
                ]
                return node

            current_root = replace_node(current_root, target_node.get("title", ""), new_node)
            click.echo("✅ 已更新，重新展示任务树：")

        else:
            click.echo(f"无效输入，请输入 y/r/q 或 0-{len(flat)-1} 的编号", err=True)


# ── 顶层命令组 ────────────────────────────────────────

@click.group("architect")
def architect_group() -> None:
    """架构师命令组：AI 辅助设计任务、分解任务、管理仓库。"""
    pass


# ── design 命令（核心：AI 辅助设计+审查+打回） ────────

@architect_group.command("design")
@click.argument("repo_name")
@click.option("--requirement", "-r", default=None, help="需求描述（不填则交互输入）")
@click.option("--model", default=None, help="LLM 模型，默认读配置文件")
def design(repo_name: str, requirement: Optional[str], model: Optional[str]) -> None:
    """AI 辅助设计任务树并提交到平台。

    \b
    流程：
      1. 输入需求描述
      2. AI 使用架构师 system prompt 生成任务树
      3. 用户逐条审查，可打回某条让 AI 修改
      4. 确认后自动创建仓库并提交任务树
    """
    config = load_config()
    api_key = config.llm.api_key
    if not api_key:
        click.echo("❌ 未配置 LLM API Key，请在 ~/.agenthub/config.yaml 中设置 llm.api_key", err=True)
        sys.exit(1)

    llm_model = model or config.llm.model or "claude-opus-4-5"
    client, auth = _make_client()

    # 1. 拉取架构师 system prompt
    system_prompt = _get_architect_prompt(client)
    if not system_prompt:
        click.echo("⚠️  无法从后端获取架构师提示词，使用内置默认提示词", err=True)
        system_prompt = (
            "你是一名系统架构师。请将用户的需求分解为层级任务树，"
            "以 JSON 格式输出，包含 repo_name 和 root_task 字段。"
            "root_task 包含 title、description、required_role、children 等字段。"
        )

    # 2. 获取需求描述
    if not requirement:
        click.echo(f"\n仓库：{repo_name}")
        click.echo("请描述你的需求（多行输入，输入空行结束）：")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        requirement = "\n".join(lines)

    if not requirement.strip():
        click.echo("❌ 需求描述不能为空", err=True)
        sys.exit(1)

    user_msg = f"仓库名：{repo_name}\n\n需求：{requirement}"

    # 3. AI 生成任务树
    raw = _call_ai_design(system_prompt, user_msg, api_key, llm_model)
    data = _extract_json(raw)
    if not data:
        click.echo("\n❌ AI 输出无法解析为 JSON，请重试", err=True)
        sys.exit(1)

    root_task = data.get("root_task", data)

    # 4. 用户审查+打回循环
    confirmed_root = _review_loop(root_task, repo_name, api_key, llm_model, system_prompt, user_msg)
    if confirmed_root is None:
        sys.exit(0)

    # 5. 创建仓库（如果不存在）
    click.echo(f"\n📁 确保仓库 {repo_name} 存在...")
    try:
        client.create_repo(repo_name)
        click.echo(f"   ✅ 仓库已创建")
    except APIError as e:
        if "already exists" in str(e) or "409" in str(e):
            click.echo(f"   ℹ️  仓库已存在，跳过创建")
        else:
            click.echo(f"   ❌ 创建仓库失败：{e}", err=True)
            sys.exit(1)

    # 6. 提交任务树
    click.echo("📤 提交任务树到平台...")
    try:
        result = client.create_decomposed_bounties(repo_name, confirmed_root)
        total = result.get("total_created", 0)
        bounties = result.get("bounties", [])
        click.echo(f"\n✅ 成功创建 {total} 个任务：\n")
        for b in bounties:
            status_icon = "⏳" if b.get("status") == "pending" else "🟢"
            deps = b.get("dependencies") or []
            dep_str = f"  (等待 {len(deps)} 个依赖)" if deps else ""
            click.echo(f"  {status_icon} [{b.get('status',''):<10}] {str(b.get('id',''))[:8]}...  {b.get('title','')}{dep_str}")
    except APIError as e:
        click.echo(f"❌ 提交失败：{e}", err=True)
        sys.exit(1)


# ── repo 子命令组 ─────────────────────────────────────

@architect_group.group("repo")
def repo_group() -> None:
    """仓库管理。"""
    pass


@repo_group.command("create")
@click.argument("name")
def repo_create(name: str) -> None:
    """创建新仓库。NAME 格式为 owner/repo，例如 myorg/myproject。"""
    if "/" not in name:
        click.echo("错误：仓库名格式应为 owner/repo，例如 myorg/myproject", err=True)
        sys.exit(1)
    client, _ = _make_client()
    try:
        result = client.create_repo(name)
        click.echo(f"✅ 仓库创建成功")
        click.echo(f"   ID       : {result['id']}")
        click.echo(f"   名称     : {result['full_name']}")
    except APIError as e:
        click.echo(f"❌ 创建失败：{e}", err=True)
        sys.exit(1)


@repo_group.command("list")
def repo_list() -> None:
    """列出所有仓库。"""
    client, _ = _make_client()
    try:
        repos = client.list_repos_full()
        if not repos:
            click.echo("暂无仓库")
            return
        click.echo(f"{'名称':<30} {'ID':<38} {'创建时间'}")
        click.echo("─" * 80)
        for r in repos:
            created = (r.get("created_at") or "")[:10]
            click.echo(f"{r['full_name']:<30} {r['id']:<38} {created}")
    except APIError as e:
        click.echo(f"❌ 获取失败：{e}", err=True)
        sys.exit(1)


# ── task 子命令组 ─────────────────────────────────────

@architect_group.group("task")
def task_group() -> None:
    """任务管理。"""
    pass


@task_group.command("create")
@click.option("--title", "-t", prompt="任务标题", help="任务标题")
@click.option("--repo", "-r", prompt="仓库名 (owner/repo)", help="所属仓库")
@click.option("--desc", "-d", default="", help="任务描述")
@click.option("--test-cmd", default="pytest", help="测试命令，默认 pytest")
@click.option("--hours", default=None, type=int, help="预估工时（小时）")
def task_create(title: str, repo: str, desc: str, test_cmd: str, hours: Optional[int]) -> None:
    """手动创建单个任务（不使用 AI）。"""
    click.echo("\n指派给哪个角色：")
    for i, r in enumerate(VALID_ROLES, 1):
        click.echo(f"  {i}. {r:<12} {ROLE_LABELS[r]}")
    while True:
        choice = click.prompt("\n输入编号", default="2")
        if choice.isdigit() and 1 <= int(choice) <= len(VALID_ROLES):
            role = VALID_ROLES[int(choice) - 1]
            break
        click.echo(f"请输入 1-{len(VALID_ROLES)} 之间的数字", err=True)

    if not desc:
        desc = click.prompt("任务描述（可选，直接回车跳过）", default="")

    client, _ = _make_client()
    try:
        result = client.create_bounty(
            title=title, repo_name=repo, description=desc,
            required_role=role, test_command=test_cmd, estimated_hours=hours,
        )
        click.echo(f"\n✅ 任务创建成功")
        click.echo(f"   ID       : {result['id']}")
        click.echo(f"   标题     : {result['title']}")
        click.echo(f"   角色     : {result['required_role']}")
        click.echo(f"   状态     : {result['status']}")
    except APIError as e:
        click.echo(f"❌ 创建失败：{e}", err=True)
        sys.exit(1)


@task_group.command("list")
@click.option("--repo", "-r", default=None, help="按仓库过滤")
@click.option("--status", "-s", default=None, help="按状态过滤 (open/in_progress/completed...)")
@click.option("--role", default=None, help="按角色过滤")
def task_list(repo: Optional[str], status: Optional[str], role: Optional[str]) -> None:
    """列出任务。"""
    client, _ = _make_client()
    try:
        bounties = client.list_bounties(repo_name=repo, status_filter=status, required_role=role)
        if not bounties:
            click.echo("暂无任务")
            return
        click.echo(f"\n{'ID':<38} {'状态':<14} {'角色':<12} {'标题'}")
        click.echo("─" * 90)
        for b in bounties:
            bid = str(b.get("id", ""))[:36]
            click.echo(f"{bid:<38} {b.get('status',''):<14} {b.get('required_role',''):<12} {b.get('title','')[:40]}")
    except APIError as e:
        click.echo(f"❌ 获取失败：{e}", err=True)
        sys.exit(1)


@task_group.command("show")
@click.argument("bounty_id")
def task_show(bounty_id: str) -> None:
    """查看任务详情。"""
    client, _ = _make_client()
    try:
        b = client.get_bounty_raw(bounty_id)
        click.echo(f"\n{'─'*50}")
        click.echo(f"  ID       : {b.get('id')}")
        click.echo(f"  标题     : {b.get('title')}")
        click.echo(f"  状态     : {b.get('status')}")
        click.echo(f"  角色     : {b.get('required_role')}")
        click.echo(f"  仓库     : {b.get('repo_name')}")
        click.echo(f"  指派给   : {b.get('assignee') or '未指派'}")
        click.echo(f"  测试命令 : {b.get('test_command')}")
        desc = b.get("description", "")
        if desc:
            click.echo(f"\n  描述：\n  {desc[:300]}")
        deps = b.get("dependencies") or []
        if deps:
            click.echo(f"\n  依赖任务：")
            for d in deps:
                click.echo(f"    - {d}")
        click.echo(f"{'─'*50}")
    except APIError as e:
        click.echo(f"❌ 获取失败：{e}", err=True)
        sys.exit(1)


@task_group.command("cancel")
@click.argument("bounty_id")
@click.option("--reason", "-r", default="", help="取消原因")
def task_cancel(bounty_id: str, reason: str) -> None:
    """取消任务。"""
    client, _ = _make_client()
    try:
        client.cancel_bounty(bounty_id, reason)
        click.echo(f"✅ 任务 {bounty_id[:8]}... 已取消")
    except APIError as e:
        click.echo(f"❌ 取消失败：{e}", err=True)
        sys.exit(1)


# ── review 命令（审查已提交任务：批准/打回） ──────────

@architect_group.command("review")
@click.argument("bounty_id", required=False, default=None)
def review(bounty_id: Optional[str]) -> None:
    """审查已提交的任务，选择批准或打回（附反馈）。

    \b
    示例：
      agenthub architect review
      agenthub architect review <bounty_id>
    """
    console = Console()
    client, _ = _make_client()

    # ── 1. 若未提供 bounty_id，列出所有已提交任务供选择 ──
    if not bounty_id:
        try:
            submitted = client.list_bounties(status_filter="submitted")
        except APIError as e:
            console.print(f"[red]❌ 获取已提交任务失败：{e}[/red]", err=True)
            sys.exit(1)

        if not submitted:
            console.print("[dim]暂无处于 submitted 状态的任务[/dim]")
            return

        # 显示编号列表
        console.print("\n[bold]已提交待审查的任务：[/bold]\n")
        for i, b in enumerate(submitted, 1):
            bid_short = str(b.get("id", ""))[:8] + "..."
            title = b.get("title", "（无标题）")
            repo = b.get("repo_name", "")
            console.print(f"  [cyan]{i:>3}.[/cyan] {title}  [dim]{bid_short}  {repo}[/dim]")

        console.print()
        choice_str = click.prompt("请输入编号选择任务", default="1")
        if not choice_str.isdigit() or not (1 <= int(choice_str) <= len(submitted)):
            console.print(f"[red]❌ 无效编号，请输入 1-{len(submitted)} 之间的数字[/red]", err=True)
            sys.exit(1)

        bounty_id = str(submitted[int(choice_str) - 1]["id"])

    # ── 2. 获取任务详情并渲染规格说明 ────────────────────
    try:
        bounty = client.get_bounty_raw(bounty_id)
    except APIError as e:
        console.print(f"[red]❌ 获取任务失败：{e}[/red]", err=True)
        sys.exit(1)

    spec = bounty.get("spec") or {}
    architect_spec = spec.get("architect") or {}
    contributor_spec = spec.get("contributor") or {}
    status = bounty.get("status", "")

    # 左列：架构师字段
    arch_table = Table(show_header=False, box=None, padding=(0, 1))
    arch_table.add_column("字段", style="bold cyan", min_width=16)
    arch_table.add_column("内容", style="white", min_width=30)

    arch_fields = [
        ("标题",     architect_spec.get("title") or bounty.get("title") or ""),
        ("描述",     architect_spec.get("description") or bounty.get("description") or ""),
        ("所需角色", architect_spec.get("required_role") or bounty.get("required_role") or ""),
        ("预估工时", str(architect_spec.get("estimated_hours")) if architect_spec.get("estimated_hours") is not None else ""),
        ("轨道",     architect_spec.get("track") or ""),
    ]
    for label, value in arch_fields:
        if value:
            arch_table.add_row(label, value)

    acceptance = architect_spec.get("acceptance_criteria") or []
    if acceptance:
        criteria_text = "\n".join(f"• {c}" for c in acceptance)
        arch_table.add_row("验收标准", criteria_text)

    arch_panel = Panel(arch_table, title="[bold blue]架构师规格[/bold blue]", border_style="blue")

    # 右列：贡献者字段
    contrib_table = Table(show_header=False, box=None, padding=(0, 1))
    contrib_table.add_column("字段", style="bold green", min_width=16)
    contrib_table.add_column("内容", style="white", min_width=30)

    contrib_fields = [
        ("实现计划",   contributor_spec.get("implementation_plan")),
        ("技术决策",   contributor_spec.get("technical_decisions")),
        ("实现备注",   contributor_spec.get("implementation_notes")),
        ("测试结果",   contributor_spec.get("test_results")),
    ]
    has_contrib = False
    for label, value in contrib_fields:
        if value is not None:
            contrib_table.add_row(label, str(value))
            has_contrib = True

    files_changed = contributor_spec.get("files_changed") or []
    if files_changed:
        contrib_table.add_row("修改文件", "\n".join(files_changed))
        has_contrib = True

    if not has_contrib:
        contrib_table.add_row("[dim]（贡献者尚未填写）[/dim]", "")

    contrib_panel = Panel(contrib_table, title="[bold green]贡献者字段[/bold green]", border_style="green")

    # 并排显示
    console.print(f"\n[bold]任务 ID：[/bold]{bounty_id}  [bold]状态：[/bold]{status}\n")
    console.print(Columns([arch_panel, contrib_panel], equal=True, expand=True))

    # 状态历史（完整规格，复用 render_spec 的状态历史部分）
    system_spec = spec.get("system") or {}
    status_history = system_spec.get("status_history") or []
    if status_history:
        hist_table = Table(show_header=True, box=None, padding=(0, 1))
        hist_table.add_column("时间戳", style="dim", min_width=20)
        hist_table.add_column("操作者类型", style="cyan", min_width=12)
        hist_table.add_column("从", style="yellow", min_width=12)
        hist_table.add_column("到", style="green", min_width=12)
        for entry in status_history:
            hist_table.add_row(
                entry.get("timestamp", "")[:19],
                entry.get("actor_type", ""),
                entry.get("from_status", ""),
                entry.get("to_status", ""),
            )
        console.print(Panel(hist_table, title="[bold yellow]状态历史[/bold yellow]", border_style="yellow"))

    # ── 3. 批准 / 打回 提示 ───────────────────────────────
    console.print("\n[bold]请选择操作：[/bold]")
    console.print("  [a] 批准（Approve）")
    console.print("  [r] 打回并附反馈（Reject with feedback）")
    console.print("  [q] 取消，不做任何操作")

    action = click.prompt("\n请输入选项", default="q").strip().lower()

    if action == "q":
        console.print("[dim]已取消，未做任何操作[/dim]")
        return

    elif action == "a":
        # 批准：调用 governance-transition?to_status=completed
        try:
            resp = client._client.post(
                f"/api/v1/bounties/{bounty_id}/governance-transition",
                params={"to_status": "completed"},
                headers=client._auth.get_auth_headers(),
            )
            if resp.status_code < 400:
                console.print(Panel(
                    f"[bold green]✅ 任务已批准并标记为 completed！[/bold green]\n[dim]ID: {bounty_id}[/dim]",
                    title="[bold green]批准成功[/bold green]",
                    border_style="green",
                ))
            elif resp.status_code == 409:
                try:
                    detail = resp.json().get("detail") or resp.text
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ 状态冲突（409）：{detail}[/red]", err=True)
                sys.exit(1)
            else:
                try:
                    detail = resp.json().get("detail") or resp.text
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ 批准失败（HTTP {resp.status_code}）：{detail}[/red]", err=True)
                sys.exit(1)
        except APIError as e:
            console.print(f"[red]❌ 批准请求失败：{e}[/red]", err=True)
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]❌ 批准请求异常：{e}[/red]", err=True)
            sys.exit(1)

    elif action == "r":
        # 打回：提示输入反馈文本，调用 POST /bounties/{id}/reject
        feedback_text = click.prompt("请输入打回反馈（将发送给贡献者）").strip()
        if not feedback_text:
            console.print("[red]❌ 反馈内容不能为空[/red]", err=True)
            sys.exit(1)

        try:
            resp = client._client.post(
                f"/api/v1/bounties/{bounty_id}/reject",
                json={"feedback": feedback_text},
                headers=client._auth.get_auth_headers(),
            )
            if resp.status_code < 400:
                console.print(Panel(
                    f"[bold yellow]🔁 任务已打回，状态已变更为 in_progress[/bold yellow]\n"
                    f"[dim]ID: {bounty_id}[/dim]\n\n"
                    f"[bold]反馈内容：[/bold]\n{feedback_text}",
                    title="[bold yellow]打回成功[/bold yellow]",
                    border_style="yellow",
                ))
            elif resp.status_code == 409:
                try:
                    detail = resp.json().get("detail") or resp.text
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ 状态冲突（409）：{detail}[/red]", err=True)
                sys.exit(1)
            else:
                try:
                    detail = resp.json().get("detail") or resp.text
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ 打回失败（HTTP {resp.status_code}）：{detail}[/red]", err=True)
                sys.exit(1)
        except APIError as e:
            console.print(f"[red]❌ 打回请求失败：{e}[/red]", err=True)
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]❌ 打回请求异常：{e}[/red]", err=True)
            sys.exit(1)

    else:
        console.print(f"[red]❌ 无效选项 '{action}'，请输入 a、r 或 q[/red]", err=True)
        sys.exit(1)


# ── 注册 book 子命令组到 task_group ───────────────────

task_group.add_command(book_group)


"""book 命令组：任务书查看与管理（task book show / view / plan / export）。"""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import load_config
from ..auth import AuthModule
from ..http_client import AgentHubClient, APIError, BountyLockedError

# 状态 emoji 映射
STATUS_EMOJI: dict[str, str] = {
    "completed":   "✅",
    "in_progress": "🔄",
    "pending":     "⏳",
    "open":        "📋",
    "submitted":   "🔁",
    "cancelled":   "❌",
}


def _make_client() -> AgentHubClient:
    config = load_config()
    auth = AuthModule()
    return AgentHubClient(base_url=config.api_base_url, auth=auth)


def _status_label(status: str) -> str:
    emoji = STATUS_EMOJI.get(status, "❓")
    return f"{emoji} {status}"


def render_spec(spec: dict | None, console: Console, bounty_id: str = "", status: str = "") -> None:
    """将 Task_Spec 渲染到 Rich Console。

    此函数可被其他命令（如 claim）复用。

    Args:
        spec: 从 API 返回的 spec 字典，可为 None（旧版 bounty）。
        console: Rich Console 实例。
        bounty_id: 可选，用于标题显示。
        status: 可选，bounty 当前状态。
    """
    if not spec:
        console.print(Panel("[dim]此任务暂无规格说明（旧版任务）[/dim]", title="Task Spec"))
        return

    architect = spec.get("architect") or {}
    contributor = spec.get("contributor") or {}
    system = spec.get("system") or {}

    # ── 标题行 ────────────────────────────────────────
    title_text = architect.get("title") or bounty_id or "（无标题）"
    status_label = _status_label(status) if status else ""
    header = f"[bold]{title_text}[/bold]"
    if status_label:
        header += f"  {status_label}"
    if bounty_id:
        header += f"\n[dim]{bounty_id}[/dim]"

    # ── 最新拒绝反馈（如有）────────────────────────────
    review_history = system.get("review_history") or []
    if review_history and review_history[-1].get("decision") == "rejected":
        last_rejection = review_history[-1]
        feedback = last_rejection.get("feedback", "")
        reviewer = last_rejection.get("reviewer_id", "")
        ts = last_rejection.get("timestamp", "")
        rejection_text = Text()
        rejection_text.append("⚠️  最新打回反馈\n", style="bold red")
        if ts:
            rejection_text.append(f"时间：{ts}\n", style="dim")
        if reviewer:
            rejection_text.append(f"审查者：{reviewer}\n", style="dim")
        rejection_text.append(f"\n{feedback}", style="red")
        console.print(Panel(rejection_text, title="[bold red]打回反馈[/bold red]", border_style="red"))

    # ── 架构师字段 ────────────────────────────────────
    arch_table = Table(show_header=False, box=None, padding=(0, 1))
    arch_table.add_column("字段", style="bold cyan", min_width=18)
    arch_table.add_column("内容", style="white")

    arch_fields = [
        ("标题",       architect.get("title") or ""),
        ("描述",       architect.get("description") or ""),
        ("所需角色",   architect.get("required_role") or ""),
        ("预估工时",   str(architect.get("estimated_hours")) if architect.get("estimated_hours") is not None else ""),
        ("轨道",       architect.get("track") or ""),
    ]
    for label, value in arch_fields:
        if value:
            arch_table.add_row(label, value)

    # 验收标准单独处理（列表）
    acceptance = architect.get("acceptance_criteria") or []
    if acceptance:
        criteria_text = "\n".join(f"• {c}" for c in acceptance)
        arch_table.add_row("验收标准", criteria_text)

    console.print(Panel(arch_table, title="[bold blue]架构师规格[/bold blue]", border_style="blue"))

    # ── 贡献者字段（全为 null 则跳过）────────────────
    impl_plan = contributor.get("implementation_plan")
    tech_decisions = contributor.get("technical_decisions")
    notes = contributor.get("implementation_notes")

    if any(v is not None for v in [impl_plan, tech_decisions, notes]):
        contrib_table = Table(show_header=False, box=None, padding=(0, 1))
        contrib_table.add_column("字段", style="bold green", min_width=18)
        contrib_table.add_column("内容", style="white")

        if impl_plan is not None:
            contrib_table.add_row("实现计划", impl_plan)
        if tech_decisions is not None:
            contrib_table.add_row("技术决策", tech_decisions)
        if notes is not None:
            contrib_table.add_row("实现备注", notes)

        console.print(Panel(contrib_table, title="[bold green]贡献者字段[/bold green]", border_style="green"))

    # ── 状态历史 ──────────────────────────────────────
    status_history = system.get("status_history") or []
    if status_history:
        hist_table = Table(show_header=True, box=None, padding=(0, 1))
        hist_table.add_column("时间戳", style="dim", min_width=22)
        hist_table.add_column("操作者类型", style="cyan", min_width=12)
        hist_table.add_column("操作者 ID", style="dim", min_width=20)
        hist_table.add_column("从", style="yellow", min_width=12)
        hist_table.add_column("到", style="green", min_width=12)

        for entry in status_history:
            hist_table.add_row(
                entry.get("timestamp", "")[:19],
                entry.get("actor_type", ""),
                str(entry.get("actor_id", ""))[:20],
                entry.get("from_status", ""),
                entry.get("to_status", ""),
            )

        console.print(Panel(hist_table, title="[bold yellow]状态历史[/bold yellow]", border_style="yellow"))
    else:
        console.print(Panel("[dim]暂无状态历史[/dim]", title="[bold yellow]状态历史[/bold yellow]", border_style="yellow"))


# ── 顶层命令组 ────────────────────────────────────────

@click.group("book")
def book_group() -> None:
    """任务书命令组：查看单个任务规格或整个项目任务书。"""
    pass


# ── show 子命令 ───────────────────────────────────────

@book_group.command("show")
@click.argument("bounty_id")
def book_show(bounty_id: str) -> None:
    """显示单个任务的完整规格说明。

    \b
    示例：
      agenthub task book show <bounty_id>
    """
    console = Console()
    client = _make_client()

    try:
        bounty = client.get_bounty_raw(bounty_id)
    except APIError as e:
        console.print(f"[red]❌ 获取任务失败：{e}[/red]", err=True)
        sys.exit(1)

    spec = bounty.get("spec")
    status = bounty.get("status", "")

    render_spec(spec, console, bounty_id=str(bounty.get("id", bounty_id)), status=status)


# ── view 子命令 ───────────────────────────────────────

@book_group.command("view")
@click.argument("repo_name")
@click.option(
    "--filter",
    "filter_value",
    default=None,
    type=click.Choice(["submitted", "incomplete"], case_sensitive=False),
    help="过滤任务：submitted（仅已提交）或 incomplete（仅未完成）",
)
def book_view(repo_name: str, filter_value: Optional[str]) -> None:
    """以层级结构显示项目的完整任务书。

    \b
    示例：
      agenthub task book view myorg/myproject
      agenthub task book view myorg/myproject --filter submitted
      agenthub task book view myorg/myproject --filter incomplete
    """
    console = Console()
    client = _make_client()

    try:
        result = client.get_project_book(repo_name, filter=filter_value)
    except APIError as e:
        console.print(f"[red]❌ 获取任务书失败：{e}[/red]", err=True)
        sys.exit(1)

    bounties: list[dict] = result.get("bounties", [])

    if not bounties:
        filter_hint = f"（过滤条件：{filter_value}）" if filter_value else ""
        console.print(f"[dim]项目 {repo_name} 暂无任务{filter_hint}[/dim]")
        return

    # 计算每个 bounty 的深度（通过 parent_id 遍历）
    id_to_bounty: dict[str, dict] = {str(b["id"]): b for b in bounties}

    def compute_depth(bounty: dict) -> int:
        depth = 0
        current = bounty
        visited: set[str] = set()
        while True:
            parent_id = current.get("parent_id")
            if not parent_id:
                break
            parent_id_str = str(parent_id)
            if parent_id_str in visited:
                break  # 防止循环引用
            visited.add(parent_id_str)
            parent = id_to_bounty.get(parent_id_str)
            if not parent:
                break
            depth += 1
            current = parent
        return depth

    # 渲染任务书表格
    table = Table(
        show_header=True,
        box=None,
        padding=(0, 1),
        title=f"[bold]项目任务书：{repo_name}[/bold]",
    )
    table.add_column("状态", style="bold", min_width=16)
    table.add_column("任务标题", min_width=40)
    table.add_column("角色", style="cyan", min_width=12)
    table.add_column("工时", style="dim", min_width=6)
    table.add_column("ID", style="dim", min_width=10)

    for bounty in bounties:
        depth = compute_depth(bounty)
        indent = "  " * depth
        status = bounty.get("status", "")
        status_label = _status_label(status)

        title = bounty.get("title", "（无标题）")
        indented_title = f"{indent}{title}"

        role = bounty.get("required_role", "")
        hours = str(bounty.get("estimated_hours", "")) if bounty.get("estimated_hours") is not None else ""
        bid = str(bounty.get("id", ""))[:8] + "..."

        table.add_row(status_label, indented_title, role, hours, bid)

    console.print(table)
    console.print(f"\n[dim]共 {len(bounties)} 个任务[/dim]")


# ── plan 子命令 ───────────────────────────────────────

@book_group.command("plan")
@click.argument("bounty_id")
def book_plan(bounty_id: str) -> None:
    """交互式编辑任务的实现计划（贡献者专用）。

    \b
    示例：
      agenthub task book plan <bounty_id>
    """
    console = Console()
    client = _make_client()

    # 获取任务原始数据
    try:
        bounty = client.get_bounty_raw(bounty_id)
    except APIError as e:
        console.print(f"[red]❌ 获取任务失败：{e}[/red]", err=True)
        sys.exit(1)

    spec = bounty.get("spec") or {}
    contributor = spec.get("contributor") or {}

    # 显示当前贡献者字段
    existing_plan = contributor.get("implementation_plan") or ""
    existing_decisions = contributor.get("technical_decisions") or ""
    existing_notes = contributor.get("implementation_notes") or ""

    contrib_table = Table(show_header=False, box=None, padding=(0, 1))
    contrib_table.add_column("字段", style="bold green", min_width=18)
    contrib_table.add_column("内容", style="white")

    if existing_plan:
        contrib_table.add_row("实现计划", existing_plan)
    else:
        contrib_table.add_row("实现计划", "[dim]（尚未填写）[/dim]")

    if existing_decisions:
        contrib_table.add_row("技术决策", existing_decisions)
    else:
        contrib_table.add_row("技术决策", "[dim]（尚未填写）[/dim]")

    if existing_notes:
        contrib_table.add_row("实现备注", existing_notes)

    console.print(Panel(contrib_table, title="[bold green]当前贡献者字段[/bold green]", border_style="green"))

    # 使用编辑器编辑实现计划
    console.print("[dim]正在打开编辑器以编辑实现计划…[/dim]")
    edited_plan = click.edit(existing_plan or "")

    # 用户关闭编辑器但未修改时 click.edit 返回 None
    if edited_plan is None:
        new_plan = existing_plan
        console.print("[dim]实现计划未修改[/dim]")
    else:
        new_plan = edited_plan.rstrip("\n")

    # 提示输入技术决策
    new_decisions = click.prompt(
        "技术决策",
        default=existing_decisions or "",
        show_default=False,
    )

    # 构建 payload（只发送非空字段）
    payload: dict = {}
    if new_plan is not None:
        payload["implementation_plan"] = new_plan
    if new_decisions is not None:
        payload["technical_decisions"] = new_decisions

    if not payload:
        console.print("[dim]无变更，跳过更新[/dim]")
        return

    # 调用 API 更新贡献者字段
    try:
        client.patch_contributor_spec(bounty_id, payload)
    except APIError as e:
        if e.status_code == 403:
            console.print("[red]❌ 权限不足：只有被分配的贡献者才能更新此字段[/red]", err=True)
        elif e.status_code == 409:
            console.print("[red]❌ 状态冲突：只有 in_progress 状态的任务才能更新贡献者字段[/red]", err=True)
        else:
            console.print(f"[red]❌ 更新失败：{e}[/red]", err=True)
        sys.exit(1)
    except BountyLockedError as e:
        console.print(f"[red]❌ 冲突：{e}[/red]", err=True)
        sys.exit(1)

    console.print(Panel(
        "[bold green]✅ 实现计划已成功更新！[/bold green]",
        title="[bold green]更新成功[/bold green]",
        border_style="green",
    ))


# ── export 子命令 ─────────────────────────────────────

def _render_bounty_markdown(bounty: dict) -> str:
    """将单个 bounty 渲染为 Markdown 字符串。"""
    lines: list[str] = []

    status = bounty.get("status", "")
    emoji = STATUS_EMOJI.get(status, "❓")
    title = bounty.get("title", "（无标题）")
    bid = str(bounty.get("id", ""))

    # 标题行（带状态 emoji）
    lines.append(f"## {emoji} {title}")
    lines.append("")
    lines.append(f"**ID**: `{bid}`  **状态**: {status}")
    lines.append("")

    spec = bounty.get("spec") or {}
    architect = spec.get("architect") or {}
    contributor = spec.get("contributor") or {}
    system = spec.get("system") or {}

    # 架构师字段（definition list 风格）
    lines.append("### 架构师规格")
    lines.append("")

    arch_field_map = [
        ("描述",     architect.get("description")),
        ("所需角色", architect.get("required_role")),
        ("预估工时", str(architect.get("estimated_hours")) if architect.get("estimated_hours") is not None else None),
        ("轨道",     architect.get("track")),
    ]
    for label, value in arch_field_map:
        if value:
            lines.append(f"**{label}**")
            lines.append(f": {value}")
            lines.append("")

    # 验收标准
    acceptance = architect.get("acceptance_criteria") or []
    if acceptance:
        lines.append("**验收标准**")
        lines.append("")
        for criterion in acceptance:
            lines.append(f"- {criterion}")
        lines.append("")

    # 贡献者字段（仅在有内容时输出）
    impl_plan = contributor.get("implementation_plan")
    tech_decisions = contributor.get("technical_decisions")
    notes = contributor.get("implementation_notes")

    if any(v for v in [impl_plan, tech_decisions, notes]):
        lines.append("### 贡献者字段")
        lines.append("")
        if impl_plan:
            lines.append("**实现计划**")
            lines.append("")
            lines.append(impl_plan)
            lines.append("")
        if tech_decisions:
            lines.append("**技术决策**")
            lines.append("")
            lines.append(tech_decisions)
            lines.append("")
        if notes:
            lines.append("**实现备注**")
            lines.append("")
            lines.append(notes)
            lines.append("")

    # 状态历史（Markdown 表格）
    status_history = system.get("status_history") or []
    if status_history:
        lines.append("### 状态历史")
        lines.append("")
        lines.append("| 时间戳 | 操作者类型 | 操作者 ID | 变更 |")
        lines.append("|--------|-----------|----------|------|")
        for entry in status_history:
            ts = entry.get("timestamp", "")[:19]
            actor_type = entry.get("actor_type", "")
            actor_id = str(entry.get("actor_id", ""))
            from_s = entry.get("from_status", "")
            to_s = entry.get("to_status", "")
            lines.append(f"| {ts} | {actor_type} | {actor_id} | {from_s} → {to_s} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


@book_group.command("export")
@click.argument("repo_name")
@click.option(
    "--output",
    "output_path",
    default=None,
    help="覆盖默认输出文件路径",
)
def book_export(repo_name: str, output_path: Optional[str]) -> None:
    """将项目任务书导出为 Markdown 文件。

    \b
    示例：
      agenthub task book export myorg/myproject
      agenthub task book export myorg/myproject --output /tmp/book.md
    """
    console = Console()
    client = _make_client()

    # 获取项目任务书
    try:
        result = client.get_project_book(repo_name)
    except APIError as e:
        console.print(f"[red]❌ 获取任务书失败：{e}[/red]", err=True)
        sys.exit(1)

    bounties: list[dict] = result.get("bounties", [])

    # 构建 Markdown 内容
    today = date.today().strftime("%Y-%m-%d")
    md_lines: list[str] = []
    md_lines.append(f"# 项目任务书：{repo_name}")
    md_lines.append("")
    md_lines.append(f"**导出日期**: {today}  **任务数量**: {len(bounties)}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    for bounty in bounties:
        md_lines.append(_render_bounty_markdown(bounty))

    markdown_content = "\n".join(md_lines)

    # 确定输出文件路径
    if output_path:
        target_path = output_path
    else:
        # 将 repo_name 中的 "/" 替换为 "-"
        sanitized_repo = repo_name.replace("/", "-")
        target_path = f"{sanitized_repo}-task-book-{today}.md"

    # 写入文件
    try:
        abs_path = os.path.abspath(target_path)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except OSError as e:
        console.print(f"[red]❌ 写入文件失败：{e}[/red]", err=True)
        sys.exit(1)

    # 输出绝对路径到 stdout
    click.echo(abs_path)
    console.print(Panel(
        f"[bold green]✅ 任务书已导出！[/bold green]\n[dim]{abs_path}[/dim]",
        title="[bold green]导出成功[/bold green]",
        border_style="green",
    ))

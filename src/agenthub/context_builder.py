from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from .http_client import AgentHubClient
from .models import Context, FileContent, SkillConfig


class ContextBuilder:
    """根据 BountyDetail 和 SkillConfig 组装 Context。"""

    def __init__(self, client: AgentHubClient, workspace_root: str = "") -> None:
        self._client = client
        self._workspace_root = workspace_root

    def build(self, bounty_id: str, skill_config: SkillConfig) -> Context:
        # 1. 拉取 BountyDetail
        bounty = self._client.get_bounty(bounty_id)

        # 2. 读取 files_to_read 中每个文件的内容
        files: list[FileContent] = []
        for path in bounty.files_to_read:
            # 如果提供了 workspace_root 且路径为相对路径，则在工作区中查找
            if self._workspace_root and not Path(path).is_absolute():
                p = Path(self._workspace_root) / path
            else:
                p = Path(path)
            if p.exists():
                files.append(FileContent(path=str(p), content=p.read_text(encoding="utf-8"), missing=False))
            else:
                files.append(FileContent(path=str(p), content=None, missing=True))

        # 3. 渲染 system prompt 模板
        template = Template(skill_config.system_prompt_template)
        system_prompt = template.render(bounty=bounty)

        # 4. Token 预算截断（1 token ≈ 4 字符）
        budget_chars = bounty.token_budget * 4
        total_chars = sum(len(fc.content) for fc in files if fc.content is not None)

        if total_chars > budget_chars:
            # 从最后一个文件开始截断
            for i in range(len(files) - 1, -1, -1):
                if total_chars <= budget_chars:
                    break
                fc = files[i]
                if fc.content is None:
                    continue
                excess = total_chars - budget_chars
                if excess >= len(fc.content):
                    total_chars -= len(fc.content)
                    files[i] = FileContent(path=fc.path, content="", missing=fc.missing)
                else:
                    new_content = fc.content[: len(fc.content) - excess]
                    total_chars -= excess
                    files[i] = FileContent(path=fc.path, content=new_content, missing=fc.missing)

        # 5. 组装并返回 Context
        return Context(
            system_prompt=system_prompt,
            bounty=bounty,
            files=files,
            token_budget=bounty.token_budget,
        )

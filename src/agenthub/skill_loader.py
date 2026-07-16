from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agenthub.models import SkillConfig


class SkillNotFoundError(Exception):
    """Raised when the requested role skill YAML file does not exist."""


class SkillLoader:
    # skills/ 目录位于包根目录的上两级（src/agenthub/ -> src/ -> agenthub-cli/ -> skills/）
    SKILLS_DIR: Path = Path(__file__).parent.parent.parent / "skills"

    def load(self, role: str) -> SkillConfig:
        """加载 skills/{role}.yaml，角色不存在则抛出 SkillNotFoundError。"""
        skill_file = self.SKILLS_DIR / f"{role}.yaml"
        if not skill_file.exists():
            raise SkillNotFoundError(
                f"技能文件不存在：{skill_file}（角色：{role!r}）"
            )

        with skill_file.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        return SkillConfig(
            role=data["role"],
            system_prompt_template=data["system_prompt_template"],
            tool_whitelist=data["tool_whitelist"],
            path_rules=data["path_rules"],
            output_schema=data["output_schema"],
        )

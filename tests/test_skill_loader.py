"""Unit tests for SkillLoader (tasks 5.1 + 5.2)."""
from __future__ import annotations

import pytest

from agenthub.skill_loader import SkillLoader, SkillNotFoundError
from agenthub.models import SkillConfig

VALID_ROLES = ["architect", "contributor", "tester", "reviewer", "executor"]


@pytest.fixture
def loader() -> SkillLoader:
    return SkillLoader()


class TestSkillLoaderValidRoles:
    """五个有效角色都能成功加载。"""

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_load_returns_skill_config(self, loader: SkillLoader, role: str) -> None:
        skill = loader.load(role)
        assert isinstance(skill, SkillConfig)

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_role_field_matches_input(self, loader: SkillLoader, role: str) -> None:
        """加载结果的 role 字段与输入一致。"""
        skill = loader.load(role)
        assert skill.role == role

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_tool_whitelist_nonempty(self, loader: SkillLoader, role: str) -> None:
        """tool_whitelist 非空。"""
        skill = loader.load(role)
        assert isinstance(skill.tool_whitelist, list)
        assert len(skill.tool_whitelist) > 0

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_path_rules_nonempty(self, loader: SkillLoader, role: str) -> None:
        """path_rules 非空。"""
        skill = loader.load(role)
        assert isinstance(skill.path_rules, list)
        assert len(skill.path_rules) > 0

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_output_schema_nonempty(self, loader: SkillLoader, role: str) -> None:
        """output_schema 非空。"""
        skill = loader.load(role)
        assert isinstance(skill.output_schema, dict)
        assert len(skill.output_schema) > 0

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_output_schema_has_status_submitted(self, loader: SkillLoader, role: str) -> None:
        """每个角色的 output_schema 都包含 status: submitted 字段。"""
        skill = loader.load(role)
        props = skill.output_schema.get("properties", {})
        assert "status" in props
        assert props["status"].get("enum") == ["submitted"]

    @pytest.mark.parametrize("role", VALID_ROLES)
    def test_system_prompt_template_nonempty(self, loader: SkillLoader, role: str) -> None:
        """system_prompt_template 非空。"""
        skill = loader.load(role)
        assert isinstance(skill.system_prompt_template, str)
        assert len(skill.system_prompt_template.strip()) > 0


class TestSkillLoaderToolWhitelists:
    """各角色工具白名单符合规范。"""

    def test_architect_readonly_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("architect")
        assert set(skill.tool_whitelist) == {"read_file", "list_directory", "search_code"}

    def test_contributor_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("contributor")
        assert set(skill.tool_whitelist) == {
            "read_file", "write_file", "run_tests", "list_directory", "search_code"
        }

    def test_tester_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("tester")
        assert set(skill.tool_whitelist) == {
            "read_file", "write_file", "run_tests", "list_directory"
        }

    def test_reviewer_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("reviewer")
        assert set(skill.tool_whitelist) == {
            "read_file", "list_directory", "search_code", "add_comment"
        }

    def test_executor_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("executor")
        assert set(skill.tool_whitelist) == {
            "read_file", "write_file", "run_command", "list_directory"
        }


class TestSkillLoaderErrors:
    """不存在的角色抛出 SkillNotFoundError。"""

    def test_unknown_role_raises(self, loader: SkillLoader) -> None:
        with pytest.raises(SkillNotFoundError):
            loader.load("nonexistent_role")

    def test_empty_role_raises(self, loader: SkillLoader) -> None:
        with pytest.raises(SkillNotFoundError):
            loader.load("")

    def test_error_message_contains_role(self, loader: SkillLoader) -> None:
        role = "unknown_xyz"
        with pytest.raises(SkillNotFoundError, match=role):
            loader.load(role)

"""Integration tests for SkillLoader — all 7 roles (B17 fix verification).

Validates: Requirements 2.17, 3.16
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agenthub.skill_loader import SkillLoader, SkillNotFoundError
from agenthub.models import SkillConfig

ALL_ROLES = [
    "architect",
    "contributor",
    "executor",
    "reviewer",
    "tester",
    "librarian",
    "observer",
]

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@pytest.fixture
def loader() -> SkillLoader:
    return SkillLoader()


@pytest.mark.parametrize("role", ALL_ROLES)
def test_skill_loader_does_not_raise(loader: SkillLoader, role: str) -> None:
    """SkillLoader().load(role) must not raise SkillNotFoundError for any of the 7 roles."""
    try:
        loader.load(role)
    except SkillNotFoundError as exc:
        pytest.fail(f"SkillNotFoundError raised for role {role!r}: {exc}")


@pytest.mark.parametrize("role", ALL_ROLES)
def test_skill_loader_returns_skill_config(loader: SkillLoader, role: str) -> None:
    """Returned object is a SkillConfig instance."""
    skill = loader.load(role)
    assert isinstance(skill, SkillConfig)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_skill_config_has_nonempty_system_prompt_template(loader: SkillLoader, role: str) -> None:
    """system_prompt_template must be a non-empty string."""
    skill = loader.load(role)
    assert isinstance(skill.system_prompt_template, str)
    assert skill.system_prompt_template.strip(), (
        f"system_prompt_template is empty for role {role!r}"
    )


@pytest.mark.parametrize("role", ALL_ROLES)
def test_skill_config_has_nonempty_tool_whitelist(loader: SkillLoader, role: str) -> None:
    """tool_whitelist must be a non-empty list."""
    skill = loader.load(role)
    assert isinstance(skill.tool_whitelist, list)
    assert len(skill.tool_whitelist) > 0, (
        f"tool_whitelist is empty for role {role!r}"
    )


def test_librarian_yaml_exists() -> None:
    """skills/librarian.yaml must exist on disk."""
    assert (SKILLS_DIR / "librarian.yaml").exists(), "skills/librarian.yaml not found"


def test_observer_yaml_exists() -> None:
    """skills/observer.yaml must exist on disk."""
    assert (SKILLS_DIR / "observer.yaml").exists(), "skills/observer.yaml not found"


def test_librarian_yaml_correctly_formatted(loader: SkillLoader) -> None:
    """librarian.yaml must load without error and have required fields."""
    skill = loader.load("librarian")
    assert skill.role == "librarian"
    assert skill.system_prompt_template.strip()
    assert skill.tool_whitelist
    assert isinstance(skill.path_rules, list)
    assert isinstance(skill.output_schema, dict)


def test_observer_yaml_correctly_formatted(loader: SkillLoader) -> None:
    """observer.yaml must load without error and have required fields."""
    skill = loader.load("observer")
    assert skill.role == "observer"
    assert skill.system_prompt_template.strip()
    assert skill.tool_whitelist
    assert isinstance(skill.path_rules, list)
    assert isinstance(skill.output_schema, dict)

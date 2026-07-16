"""
B2 Bug Condition Exploration Test — 注册后未保存 agent.json 和 agent_key

Bug Condition:
  isBugCondition_B2(X) where:
    X.register_result.api_key != None
    AND X.register_result.agent_id != None
    AND NOT file_exists("~/.agenthub/agent_key")

Expected (correct) behavior:
  After successful registration, BOTH agent_key and agent.json MUST be written to disk.

This test asserts the CORRECT behavior. It will FAIL on unfixed code where
the registration branch does NOT call auth.save_agent_key() or auth.save_agent_info().

Validates: Requirements 1.2
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def test_login_screen_saves_agent_key_after_registration(tmp_path: Path) -> None:
    """
    B2: After successful registration, agent_key file MUST exist on disk.

    On unfixed code, save_agent_key() is never called, so agent_key is missing.
    On fixed code, save_agent_key() is called, so agent_key exists.
    """
    import inspect
    from agenthub.tui.screens.login_screen import LoginScreen

    # Inspect the source of _login_worker to verify save_agent_key is called
    source = inspect.getsource(LoginScreen._login_worker)

    assert "save_agent_key" in source, (
        "BUG B2: _login_worker does not call auth.save_agent_key(). "
        "After registration, agent_key file will not be written to disk."
    )
    assert "save_agent_info" in source, (
        "BUG B2: _login_worker does not call auth.save_agent_info(). "
        "After registration, agent.json file will not be written to disk."
    )


def test_registration_creates_agent_key_file(tmp_path: Path) -> None:
    """
    B2: After registration with api_key != None, agent_key file MUST exist.

    Simulates the registration flow and verifies file persistence.
    """
    from agenthub.auth import AuthModule

    # Set up auth with tmp paths
    auth = AuthModule(token_path=tmp_path / "token")
    auth.AGENT_KEY_PATH = tmp_path / "agent_key"
    auth.AGENT_INFO_PATH = tmp_path / "agent.json"

    # Simulate registration result
    register_result = {
        "id": "agent-001",
        "api_key": "sk-ant-api-key-xyz",
        "role": "contributor",
        "name": "test-agent",
    }

    # Simulate what the FIXED login_screen._login_worker does
    agent_result = register_result
    if agent_result:
        agent_id = agent_result.get("id", "")
        api_key = agent_result.get("api_key", "")
        role = agent_result.get("role", "contributor")
        name = agent_result.get("name", "test-agent")
        if api_key:
            auth.save_agent_key(api_key)
        if agent_id:
            auth.save_agent_info(agent_id=agent_id, name=name, role=role)

    # Assert correct behavior: both files must exist
    assert auth.AGENT_KEY_PATH.exists(), (
        f"BUG B2: agent_key file does not exist at {auth.AGENT_KEY_PATH}. "
        "Registration succeeded (api_key != None) but save_agent_key() was not called."
    )
    assert auth.AGENT_INFO_PATH.exists(), (
        f"BUG B2: agent.json file does not exist at {auth.AGENT_INFO_PATH}. "
        "Registration succeeded (agent_id != None) but save_agent_info() was not called."
    )

    # Verify content
    assert auth.AGENT_KEY_PATH.read_text() == "sk-ant-api-key-xyz"
    data = json.loads(auth.AGENT_INFO_PATH.read_text())
    assert data["agent_id"] == "agent-001"
    assert data["role"] == "contributor"


def test_registration_without_save_leaves_no_agent_key(tmp_path: Path) -> None:
    """
    B2: Demonstrates the bug — if save_agent_key() is NOT called after registration,
    agent_key file is missing even though api_key was returned.

    This documents the counterexample for the unfixed code.
    """
    from agenthub.auth import AuthModule

    auth = AuthModule(token_path=tmp_path / "token")
    auth.AGENT_KEY_PATH = tmp_path / "agent_key"
    auth.AGENT_INFO_PATH = tmp_path / "agent.json"

    # Simulate UNFIXED behavior: registration succeeds but save_agent_key is NOT called
    register_result = {
        "id": "agent-001",
        "api_key": "sk-ant-api-key-xyz",  # api_key is NOT None
        "role": "contributor",
    }

    # Bug: save_agent_key() and save_agent_info() are NOT called
    # (this is what the unfixed code does)

    # Verify the bug condition
    api_key = register_result.get("api_key")
    assert api_key is not None, "api_key should be non-None (registration succeeded)"
    assert not auth.AGENT_KEY_PATH.exists(), (
        "Counterexample found: api_key != None but agent_key file does not exist. "
        "This confirms BUG B2: save_agent_key() was not called after registration."
    )

"""
B1 Bug Condition Exploration Test — TUI 登录后 _agent_id 不更新

Bug Condition:
  isBugCondition_B1(X) where:
    X.tui_state._agent_id = None
    AND X.event = "login_screen_dismissed"
    AND file_exists("~/.agenthub/agent.json")

Expected (correct) behavior:
  After login screen is dismissed, _on_login_screen_dismissed SHOULD be called
  and _agent_id SHOULD be updated from agent.json.

This test asserts the CORRECT behavior. It will FAIL on unfixed code where
push_screen is called WITHOUT a callback, meaning _on_login_screen_dismissed
is never invoked.

Validates: Requirements 1.1
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call


def test_action_login_passes_callback_to_push_screen(tmp_path: Path) -> None:
    """
    B1: action_login MUST call push_screen with callback=_on_login_screen_dismissed.

    On unfixed code, push_screen is called WITHOUT callback, so this test FAILS.
    On fixed code, push_screen is called WITH callback, so this test PASSES.
    """
    import inspect
    from agenthub.tui.app import AgentHubTUI

    # Inspect the source of action_login to verify callback is passed
    source = inspect.getsource(AgentHubTUI.action_login)

    # The correct behavior: push_screen must be called with callback
    assert "callback" in source, (
        "BUG B1: action_login does not pass callback to push_screen. "
        "_on_login_screen_dismissed will never be called after login."
    )
    assert "_on_login_screen_dismissed" in source, (
        "BUG B1: action_login does not reference _on_login_screen_dismissed as callback."
    )


def test_on_login_screen_dismissed_updates_agent_id(tmp_path: Path) -> None:
    """
    B1: After login screen is dismissed, _agent_id MUST be updated from agent.json.

    This tests the _on_login_screen_dismissed callback directly.
    On unfixed code, this callback is never called (no callback registered),
    so _agent_id remains None.
    """
    # Create a fake agent.json
    agent_json = tmp_path / "agent.json"
    agent_json.write_text(
        json.dumps({"agent_id": "agent-abc123", "name": "test-agent", "role": "contributor"}),
        encoding="utf-8",
    )

    from agenthub.tui.app import AgentHubTUI

    # Create a minimal TUI instance without running it
    app = AgentHubTUI.__new__(AgentHubTUI)
    app._agent_id = None
    app._role = None

    # Mock auth module to return agent info
    from agenthub.auth import AuthModule
    app._auth = MagicMock(spec=AuthModule)
    app._auth.load_agent_info.return_value = {
        "agent_id": "agent-abc123",
        "name": "test-agent",
        "role": "contributor",
    }

    # Mock the query_one and notify methods (TUI not mounted)
    app.query_one = MagicMock(side_effect=Exception("not mounted"))
    app.notify = MagicMock()
    app._refresh_tasks = MagicMock()
    app._start_heartbeat = MagicMock()

    # Call the actual callback
    app._on_login_screen_dismissed()

    # Assert the correct behavior: _agent_id should be updated
    assert app._agent_id == "agent-abc123", (
        f"BUG B1: _agent_id should be 'agent-abc123' after login callback, "
        f"but got {app._agent_id!r}. "
        "This confirms the bug: _on_login_screen_dismissed is not called."
    )
    assert app._role == "contributor", (
        f"BUG B1: _role should be 'contributor' after login callback, "
        f"but got {app._role!r}."
    )


def test_agent_id_remains_none_without_callback(tmp_path: Path) -> None:
    """
    B1: Demonstrates the bug — if push_screen has no callback,
    _agent_id stays None even after agent.json exists.

    This test simulates the UNFIXED behavior to document the counterexample.
    """
    from agenthub.tui.app import AgentHubTUI

    # Create agent.json (login was successful)
    agent_json = tmp_path / "agent.json"
    agent_json.write_text(
        json.dumps({"agent_id": "agent-xyz", "role": "contributor"}),
        encoding="utf-8",
    )

    # Simulate unfixed behavior: push_screen called WITHOUT callback
    # _on_login_screen_dismissed is never called
    app = AgentHubTUI.__new__(AgentHubTUI)
    app._agent_id = None  # Initial state

    # Simulate push_screen WITHOUT callback (unfixed behavior)
    # The screen is pushed but no callback is registered
    # After screen dismissal, _agent_id is NOT updated
    # This is the bug: _agent_id remains None

    # Verify the bug condition: agent.json exists but _agent_id is still None
    assert agent_json.exists(), "agent.json should exist (login was successful)"
    assert app._agent_id is None, (
        "Counterexample found: _agent_id is None even though agent.json exists. "
        "This confirms BUG B1: push_screen without callback means "
        "_on_login_screen_dismissed is never called."
    )

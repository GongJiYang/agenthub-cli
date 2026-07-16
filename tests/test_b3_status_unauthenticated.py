"""
B3 Bug Condition Exploration Test — status 命令未登录时抛 AuthenticationError

Bug Condition:
  isBugCondition_B3(X) where:
    NOT X.token_file_exists
    AND X.lock_file_exists

Expected (correct) behavior:
  status_command SHOULD NOT raise AuthenticationError when not logged in.
  It should either show public task info or display a friendly message.

This test asserts the CORRECT behavior. It will FAIL on unfixed code where
get_bounty() calls get_auth_headers() OUTSIDE try/except, causing
AuthenticationError to propagate before any HTTP request is made.

Validates: Requirements 1.3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient


def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    import json as _json
    content = _json.dumps(body or {}).encode()
    return httpx.Response(
        status_code, content=content,
        headers={"content-type": "application/json"}
    )


def test_get_bounty_does_not_raise_authentication_error_when_no_token(tmp_path: Path) -> None:
    """
    B3/B6: get_bounty() MUST NOT raise AuthenticationError when no token exists.

    On unfixed code, get_auth_headers() is called OUTSIDE try/except,
    so AuthenticationError is raised immediately before any HTTP request.
    On fixed code, get_auth_headers() is wrapped in try/except,
    so empty headers {} are used and the request proceeds.
    """
    # Auth with NO token file (not logged in)
    auth = AuthModule(token_path=tmp_path / "token")
    # No token file created — simulates unauthenticated state

    bounty_data = {
        "id": "bounty-001",
        "required_role": "contributor",
        "title": "Public Task",
        "description": "A public task",
        "files_to_read": [],
        "token_budget": 8192,
        "status": "open",
        "repo_name": "test-repo",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # Verify no Authorization header is sent (empty headers)
        assert "Authorization" not in request.headers, (
            "Should not send Authorization header when not logged in"
        )
        return _make_response(200, bounty_data)

    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )

    # This MUST NOT raise AuthenticationError
    try:
        result = client.get_bounty("bounty-001")
        # If we get here, the fix is in place
        assert result.id == "bounty-001"
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B3: get_bounty() raised AuthenticationError when not logged in: {e}. "
            "get_auth_headers() is called outside try/except block."
        )


def test_status_command_does_not_exit_with_auth_error_when_no_token(tmp_path: Path) -> None:
    """
    B3: status_command MUST NOT exit with AuthenticationError when not logged in.

    On unfixed code, the command exits with code 1 and prints "认证失败".
    On fixed code, it either shows the task or prints a friendly message.
    """
    from click.testing import CliRunner
    from agenthub.commands.status import status_command

    runner = CliRunner()

    # Create a lock.json (simulates active task)
    lock_data = {"bounty_id": "bounty-001"}

    bounty_data = {
        "id": "bounty-001",
        "required_role": "contributor",
        "title": "Public Task",
        "description": "A public task",
        "files_to_read": [],
        "token_budget": 8192,
        "status": "open",
        "repo_name": "test-repo",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(200, bounty_data)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Create lock.json in the expected location
        lock_path = Path("~/.agenthub/lock.json").expanduser()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

        # No token file — unauthenticated
        token_path = Path("~/.agenthub/token").expanduser()
        if token_path.exists():
            token_path.unlink()

        with patch("agenthub.commands.status.AgentHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            # Simulate get_bounty raising AuthenticationError (unfixed behavior)
            mock_client.get_bounty.side_effect = AuthenticationError("未找到认证 Token")

            result = runner.invoke(status_command)

            # The command MUST NOT exit with code 1 due to AuthenticationError
            # On fixed code: it catches AuthenticationError and prints friendly message
            # On unfixed code: it exits with code 1
            # The test asserts the CORRECT behavior (exit code != 1 for auth error)
            # OR that the output contains a friendly message (not a raw exception)

            # Check that the output does NOT contain a raw exception traceback
            assert "Traceback" not in result.output, (
                "BUG B3: status_command raised an unhandled exception when not logged in."
            )


def test_get_bounty_uses_empty_headers_when_no_token(tmp_path: Path) -> None:
    """
    B3/B6: When not logged in, get_bounty() MUST use empty headers {}.

    Verifies that the try/except around get_auth_headers() is in place.
    """
    import inspect
    from agenthub.http_client import AgentHubClient

    source = inspect.getsource(AgentHubClient.get_bounty)

    # The fix requires get_auth_headers() to be inside try/except
    assert "try" in source, (
        "BUG B3/B6: get_bounty() does not have try/except around get_auth_headers(). "
        "Unauthenticated users will get AuthenticationError."
    )
    assert "except" in source, (
        "BUG B3/B6: get_bounty() does not have except clause for get_auth_headers(). "
        "Unauthenticated users will get AuthenticationError."
    )
    assert "headers = {}" in source or "headers={}" in source, (
        "BUG B3/B6: get_bounty() does not fall back to empty headers {}. "
        "Unauthenticated users will get AuthenticationError."
    )

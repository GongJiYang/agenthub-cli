"""
B6 Bug Condition Exploration Test — 公开接口未登录时抛 AuthenticationError

Bug Condition:
  isBugCondition_B6(X) where:
    X.method_name IN {"list_bounties", "list_repos", "get_bounty"}
    AND NOT X.token_exists

Expected (correct) behavior:
  list_bounties(), list_repos(), get_bounty() MUST NOT raise AuthenticationError
  when not logged in. They should use empty headers {} and proceed with the request.

This test asserts the CORRECT behavior. It will FAIL on unfixed code where
get_auth_headers() is called OUTSIDE try/except, causing AuthenticationError
to be raised before any HTTP request is made.

Validates: Requirements 1.6
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient


def _make_response(status_code: int, body=None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code, content=content,
        headers={"content-type": "application/json"}
    )


def _make_unauthenticated_client(tmp_path: Path, handler) -> AgentHubClient:
    """Create AgentHubClient with NO token (unauthenticated)."""
    auth = AuthModule(token_path=tmp_path / "token")
    # No token file — unauthenticated

    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )
    return client


def test_list_bounties_does_not_raise_authentication_error_when_no_token(tmp_path: Path) -> None:
    """
    B6: list_bounties() MUST NOT raise AuthenticationError when not logged in.

    On unfixed code: get_auth_headers() is called outside try/except → AuthenticationError.
    On fixed code: try/except catches the error → empty headers {} used.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        # Should reach here with empty/no auth headers
        return _make_response(200, [
            {"id": "b-001", "title": "Task 1", "status": "open", "required_role": "contributor"}
        ])

    client = _make_unauthenticated_client(tmp_path, handler)

    try:
        result = client.list_bounties()
        assert isinstance(result, list), "list_bounties should return a list"
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B6: list_bounties() raised AuthenticationError when not logged in: {e}. "
            "get_auth_headers() is called outside try/except block."
        )


def test_list_repos_does_not_raise_authentication_error_when_no_token(tmp_path: Path) -> None:
    """
    B6: list_repos() MUST NOT raise AuthenticationError when not logged in.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(200, {"repos": ["repo-1", "repo-2"]})

    client = _make_unauthenticated_client(tmp_path, handler)

    try:
        result = client.list_repos()
        assert isinstance(result, list), "list_repos should return a list"
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B6: list_repos() raised AuthenticationError when not logged in: {e}. "
            "get_auth_headers() is called outside try/except block."
        )


def test_get_bounty_does_not_raise_authentication_error_when_no_token(tmp_path: Path) -> None:
    """
    B6: get_bounty() MUST NOT raise AuthenticationError when not logged in.
    """
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

    client = _make_unauthenticated_client(tmp_path, handler)

    try:
        result = client.get_bounty("bounty-001")
        assert result.id == "bounty-001"
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B6: get_bounty() raised AuthenticationError when not logged in: {e}. "
            "get_auth_headers() is called outside try/except block."
        )


def test_list_bounties_uses_empty_headers_when_no_token(tmp_path: Path) -> None:
    """
    B6: When not logged in, list_bounties() MUST use empty headers {}.
    Verifies no Authorization header is sent.
    """
    received_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers.update(dict(request.headers))
        return _make_response(200, [])

    client = _make_unauthenticated_client(tmp_path, handler)

    try:
        client.list_bounties()
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B6: list_bounties() raised AuthenticationError: {e}. "
            "Should use empty headers when not logged in."
        )

    assert "authorization" not in received_headers, (
        "BUG B6: Authorization header was sent even though user is not logged in."
    )
    assert "x-api-key" not in received_headers, (
        "BUG B6: X-API-Key header was sent even though user is not logged in."
    )


def test_list_repos_uses_empty_headers_when_no_token(tmp_path: Path) -> None:
    """
    B6: When not logged in, list_repos() MUST use empty headers {}.
    """
    received_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers.update(dict(request.headers))
        return _make_response(200, {"repos": []})

    client = _make_unauthenticated_client(tmp_path, handler)

    try:
        client.list_repos()
    except AuthenticationError as e:
        pytest.fail(
            f"BUG B6: list_repos() raised AuthenticationError: {e}. "
            "Should use empty headers when not logged in."
        )

    assert "authorization" not in received_headers, (
        "BUG B6: Authorization header was sent even though user is not logged in."
    )


def test_public_api_methods_have_try_except_around_get_auth_headers() -> None:
    """
    B6: All three public API methods MUST wrap get_auth_headers() in try/except.
    """
    import inspect
    from agenthub.http_client import AgentHubClient

    for method_name in ["list_bounties", "list_repos", "get_bounty"]:
        method = getattr(AgentHubClient, method_name)
        source = inspect.getsource(method)

        assert "try" in source, (
            f"BUG B6: {method_name}() does not have try/except around get_auth_headers(). "
            "Unauthenticated users will get AuthenticationError."
        )
        assert "except" in source, (
            f"BUG B6: {method_name}() does not have except clause. "
            "Unauthenticated users will get AuthenticationError."
        )
        assert "headers = {}" in source or "headers={}" in source, (
            f"BUG B6: {method_name}() does not fall back to empty headers {{}}. "
            "Unauthenticated users will get AuthenticationError."
        )

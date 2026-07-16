"""
B7 Bug Condition Exploration Test — 重复邮箱注册异常类型不一致

Bug Condition:
  isBugCondition_B7(X) where:
    X.http_response.status_code IN {400, 409, 422}
    AND X.http_response.endpoint = "/api/v1/auth/register"

Expected (correct) behavior:
  When registering with a duplicate email (server returns 4xx),
  the exception raised MUST be APIError (not BountyLockedError).
  Callers should use e.status_code to distinguish error types.

This test asserts the CORRECT behavior. It WILL FAIL on unfixed code because:
  - _raise_for_status raises BountyLockedError for HTTP 409
  - register_user calls _raise_for_status without special handling
  - So duplicate email (409) raises BountyLockedError instead of APIError

Validates: Requirements 1.7
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient, APIError, BountyLockedError


def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code, content=content,
        headers={"content-type": "application/json"}
    )


def _make_client(tmp_path: Path, handler) -> AgentHubClient:
    auth = AuthModule(token_path=tmp_path / "token")
    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )
    return client


def test_register_user_with_409_raises_api_error_not_bounty_locked_error(tmp_path: Path) -> None:
    """
    B7: register_user() with HTTP 409 (duplicate email) MUST raise APIError,
    NOT BountyLockedError.

    On unfixed code: _raise_for_status raises BountyLockedError for 409.
    On fixed code: register_user catches BountyLockedError and re-raises as APIError,
    OR _raise_for_status is context-aware.

    THIS TEST WILL FAIL ON UNFIXED CODE — BountyLockedError is raised instead of APIError.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/register"
        return _make_response(409, {"detail": "Email already registered"})

    client = _make_client(tmp_path, handler)

    with pytest.raises(APIError) as exc_info:
        client.register_user("existing@example.com", "password123")

    assert exc_info.value.status_code == 409, (
        f"BUG B7: Expected APIError with status_code=409, "
        f"got status_code={exc_info.value.status_code}"
    )


def test_register_user_with_422_raises_api_error(tmp_path: Path) -> None:
    """
    B7: register_user() with HTTP 422 (validation error / duplicate email)
    MUST raise APIError with status_code=422.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/register"
        return _make_response(422, {"detail": "Email already exists"})

    client = _make_client(tmp_path, handler)

    with pytest.raises(APIError) as exc_info:
        client.register_user("existing@example.com", "password123")

    assert exc_info.value.status_code == 422, (
        f"BUG B7: Expected APIError with status_code=422, "
        f"got status_code={exc_info.value.status_code}"
    )


def test_register_user_with_400_raises_api_error(tmp_path: Path) -> None:
    """
    B7: register_user() with HTTP 400 MUST raise APIError with status_code=400.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(400, {"detail": "Invalid email format"})

    client = _make_client(tmp_path, handler)

    with pytest.raises(APIError) as exc_info:
        client.register_user("bad-email", "password123")

    assert exc_info.value.status_code == 400


def test_register_user_409_does_not_raise_bounty_locked_error(tmp_path: Path) -> None:
    """
    B7: register_user() with HTTP 409 MUST NOT raise BountyLockedError.

    BountyLockedError is semantically wrong for duplicate email registration.
    This test explicitly verifies the wrong exception type is NOT raised.

    THIS TEST WILL FAIL ON UNFIXED CODE — BountyLockedError IS raised.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(409, {"detail": "Email already registered"})

    client = _make_client(tmp_path, handler)

    try:
        client.register_user("existing@example.com", "password123")
        pytest.fail("Expected an exception to be raised")
    except BountyLockedError as e:
        pytest.fail(
            f"BUG B7: register_user() raised BountyLockedError for duplicate email (409): {e}. "
            "BountyLockedError is semantically wrong for registration. "
            "Should raise APIError instead. "
            "COUNTEREXAMPLE: HTTP 409 on /api/v1/auth/register → BountyLockedError raised."
        )
    except APIError:
        pass  # Correct behavior
    except AuthenticationError:
        pytest.fail("Should not raise AuthenticationError for 409")


def test_raise_for_status_409_raises_bounty_locked_error_for_non_register_endpoints(tmp_path: Path) -> None:
    """
    Preservation: _raise_for_status MUST still raise BountyLockedError for 409
    on non-registration endpoints (e.g., claim_bounty).

    This verifies the fix doesn't break the existing 409 behavior for claim operations.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(409, {"detail": "Bounty already claimed"})

    auth = AuthModule(token_path=tmp_path / "token")
    auth.save_token("test-token")
    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )

    with pytest.raises(BountyLockedError):
        client.claim_bounty("bounty-001", "agent-001")

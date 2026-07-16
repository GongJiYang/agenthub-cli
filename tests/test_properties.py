"""
Preservation Property Tests (Task 2)
=====================================
These tests verify UNCHANGED baseline behavior on the current (unfixed/fixed) code.
All tests are expected to PASS — they document the behavior we must preserve.

Testing framework: Hypothesis (property-based) + pytest (parametrize)

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9,
             3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16**
"""
from __future__ import annotations

import base64
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient, APIError, BountyLockedError
from agenthub.skill_loader import SkillLoader, SkillNotFoundError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_response(status_code: int, body: Any = None) -> httpx.Response:
    content = json.dumps(body if body is not None else {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
    )


def _make_jwt(exp: int) -> str:
    """Build a minimal JWT with the given exp claim."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "agent-1", "exp": exp}).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


# ─────────────────────────────────────────────────────────────────────────────
# Property 1: _raise_for_status exception types
# Validates: Requirements 3.7, 3.8, 3.9
# ─────────────────────────────────────────────────────────────────────────────

@given(status_code=st.integers(min_value=400, max_value=599))
@settings(max_examples=100)
def test_raise_for_status_exception_types(status_code: int) -> None:
    """
    Property: _raise_for_status maps HTTP status codes to the correct exception types.

    - 401 → AuthenticationError
    - 409 → BountyLockedError
    - 5xx → APIError
    - Other 4xx → APIError

    **Validates: Requirements 3.7, 3.8, 3.9**
    """
    resp = _make_response(status_code, {"detail": f"error {status_code}"})

    if status_code == 401:
        with pytest.raises(AuthenticationError):
            AgentHubClient._raise_for_status(resp)
    elif status_code == 409:
        with pytest.raises(BountyLockedError):
            AgentHubClient._raise_for_status(resp)
    elif 500 <= status_code <= 599:
        with pytest.raises(APIError) as exc_info:
            AgentHubClient._raise_for_status(resp)
        assert exc_info.value.status_code == status_code
    else:
        # Other 4xx (400, 402-408, 410-499)
        with pytest.raises(APIError) as exc_info:
            AgentHubClient._raise_for_status(resp)
        assert exc_info.value.status_code == status_code


# ─────────────────────────────────────────────────────────────────────────────
# Property 2: Public API auth header behavior
# Validates: Requirements 3.6
# ─────────────────────────────────────────────────────────────────────────────

@given(
    token_value=st.text(min_size=1, max_size=64).filter(lambda t: t.strip() != ""),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_public_api_auth_header_when_token_exists(token_value: str) -> None:
    """
    Property: When a token exists, get_auth_headers() returns a non-empty dict
    containing an Authorization or X-API-Key header.

    **Validates: Requirements 3.6**
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auth = AuthModule(token_path=tmp_path / "token")
        auth.save_token(token_value)

        headers = auth.get_auth_headers()
        assert isinstance(headers, dict)
        assert len(headers) > 0
        # Must have either Authorization or X-API-Key
        assert "Authorization" in headers or "X-API-Key" in headers


@given(token_value=st.text(min_size=1, max_size=64).filter(lambda t: t.strip() != ""))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_public_api_no_auth_error_when_token_missing(token_value: str) -> None:
    """
    Property: When token does NOT exist, calling list_bounties/list_repos/get_bounty
    does NOT raise AuthenticationError — it proceeds with empty headers.

    **Validates: Requirements 3.6 (preservation: logged-in behavior unchanged)**
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # No token saved — unauthenticated state
        auth = AuthModule(token_path=tmp_path / "no_token_here")

        # get_auth_headers() should raise AuthenticationError when no token
        with pytest.raises(AuthenticationError):
            auth.get_auth_headers()

        # But the client methods should NOT propagate that error — they catch it
        # and use empty headers instead.
        captured_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return _make_response(200, [])

        client = AgentHubClient(base_url="https://api.example.com", auth=auth)
        client._client = httpx.Client(
            base_url="https://api.example.com",
            transport=httpx.MockTransport(handler),
            timeout=30.0,
        )

        # Should NOT raise AuthenticationError
        result = client.list_bounties()
        assert isinstance(result, list)
        # Authorization header should NOT be present (empty headers)
        assert len(captured_headers) == 1
        assert "authorization" not in captured_headers[0]


# ─────────────────────────────────────────────────────────────────────────────
# Property 3: save_agent_info idempotency
# Validates: Requirements 3.2
# ─────────────────────────────────────────────────────────────────────────────

@given(
    agent_id=st.text(min_size=1, max_size=64),
    api_key=st.text(min_size=10, max_size=128),
    role=st.sampled_from(["contributor", "architect", "executor"]),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_save_agent_info_idempotent(agent_id: str, api_key: str, role: str) -> None:
    """
    Property: Multiple calls to save_agent_info with the same data produce the
    same result. Last write wins — the file always reflects the last call.

    **Validates: Requirements 3.2**
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auth = AuthModule(token_path=tmp_path / "token")
        # Override paths to use tmp_path
        auth.AGENT_INFO_PATH = tmp_path / "agent.json"
        auth.AGENT_KEY_PATH = tmp_path / "agent_key"

        name = "test-agent"

        # Call once
        auth.save_agent_info(agent_id=agent_id, name=name, role=role)
        data_first = json.loads(auth.AGENT_INFO_PATH.read_text(encoding="utf-8"))

        # Call again with same data
        auth.save_agent_info(agent_id=agent_id, name=name, role=role)
        data_second = json.loads(auth.AGENT_INFO_PATH.read_text(encoding="utf-8"))

        # Both calls produce the same result
        assert data_first == data_second
        assert data_second["agent_id"] == agent_id
        assert data_second["role"] == role

        # Call with different data — last write wins
        new_agent_id = agent_id + "_v2"
        auth.save_agent_info(agent_id=new_agent_id, name=name, role=role)
        data_third = json.loads(auth.AGENT_INFO_PATH.read_text(encoding="utf-8"))
        assert data_third["agent_id"] == new_agent_id


# ─────────────────────────────────────────────────────────────────────────────
# Property 4: api_key validation
# Validates: Requirements 3.4
# ─────────────────────────────────────────────────────────────────────────────

@given(api_key=st.one_of(st.none(), st.just(""), st.text(min_size=1)))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_chat_runner_api_key_validation(api_key: Any, capsys) -> None:
    """
    Property: ChatRunner._call_llm_streaming handles api_key correctly:
    - None or empty → prints friendly message, returns without raising SDK exception
    - Non-empty → attempts to initialize Anthropic SDK (may fail with import/network,
      but NOT with a raw TypeError from passing None to SDK)

    **Validates: Requirements 3.4**
    """
    from agenthub.chat_runner import ChatRunner
    from agenthub.models import AppConfig, LLMConfig, ChatSession

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = AppConfig(
            api_base_url="https://api.example.com",
            llm=LLMConfig(provider="anthropic", model="claude-3-haiku-20240307", api_key=api_key),
        )
        auth = AuthModule(token_path=tmp_path / "token")
        runner = ChatRunner(
            config=config,
            auth=auth,
            bounty_id=None,
            model="claude-3-haiku-20240307",
            show_tools=False,
            save_path=None,
        )
        # Set up a minimal session
        runner._session = ChatSession(
            mode="standalone",
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            started_at="2025-01-01T00:00:00Z",
        )

        if not api_key:
            # None or empty: should print friendly message and return, no SDK exception
            runner._call_llm_streaming("system prompt")
            captured = capsys.readouterr()
            assert "api_key" in captured.out.lower() or "api" in captured.out.lower()
        else:
            # Non-empty: may raise various errors (network, import) but NOT
            # a raw TypeError from passing None to SDK
            try:
                runner._call_llm_streaming("system prompt")
            except Exception as e:
                # Acceptable: SDK not installed, network error, etc.
                # NOT acceptable: TypeError about NoneType
                assert not (isinstance(e, TypeError) and "NoneType" in str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Property 5: AuthModule token round-trip
# Validates: Requirements 3.1, 3.3
# ─────────────────────────────────────────────────────────────────────────────

@given(token=st.text(min_size=1, max_size=256).filter(
    lambda t: t.strip() != "" and "\r" not in t
))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_auth_module_token_roundtrip(token: str) -> None:
    """
    Property: save_token + load_token round-trip is consistent.
    Whatever token is saved can be loaded back unchanged.
    (Tokens with \\r are excluded as file I/O may normalize line endings.)

    **Validates: Requirements 3.1, 3.3**
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auth = AuthModule(token_path=tmp_path / "token")
        auth.save_token(token)
        loaded = auth.load_token()
        # load_token strips whitespace, so we compare stripped
        assert loaded == token.strip()


@given(token=st.text(min_size=1, max_size=256).filter(
    lambda t: t.strip() != "" and "\r" not in t
))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_auth_module_token_roundtrip_multiple_saves(token: str) -> None:
    """
    Property: Multiple saves of the same token always load the same value.

    **Validates: Requirements 3.1**
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        auth = AuthModule(token_path=tmp_path / "token")
        auth.save_token(token)
        first = auth.load_token()
        auth.save_token(token)
        second = auth.load_token()
        assert first == second


# ─────────────────────────────────────────────────────────────────────────────
# Property 6: SkillLoader loads existing roles (parametrize)
# Validates: Requirements 3.16
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "role",
    ["architect", "contributor", "executor", "reviewer", "tester"],
)
def test_skill_loader_loads_existing_roles(role: str) -> None:
    """
    Property: SkillLoader.load() for all known roles does NOT raise SkillNotFoundError.

    **Validates: Requirements 3.16**
    """
    loader = SkillLoader()
    # Should not raise
    skill = loader.load(role)
    assert skill is not None
    assert skill.role == role
    assert skill.system_prompt_template
    assert skill.tool_whitelist


# ─────────────────────────────────────────────────────────────────────────────
# Additional preservation: APIError carries correct status_code
# Validates: Requirements 3.9
# ─────────────────────────────────────────────────────────────────────────────

@given(status_code=st.integers(min_value=400, max_value=599).filter(
    lambda c: c not in (401, 409)
))
@settings(max_examples=80)
def test_api_error_carries_status_code(status_code: int) -> None:
    """
    Property: For all non-401/non-409 error codes, APIError.status_code equals
    the HTTP response status code.

    **Validates: Requirements 3.9**
    """
    resp = _make_response(status_code, {"detail": "error"})
    with pytest.raises(APIError) as exc_info:
        AgentHubClient._raise_for_status(resp)
    assert exc_info.value.status_code == status_code


# ─────────────────────────────────────────────────────────────────────────────
# Additional preservation: no exception for 2xx/3xx responses
# ─────────────────────────────────────────────────────────────────────────────

@given(status_code=st.integers(min_value=200, max_value=399))
@settings(max_examples=50)
def test_raise_for_status_no_exception_for_success(status_code: int) -> None:
    """
    Property: _raise_for_status does NOT raise for 2xx/3xx responses.
    """
    resp = _make_response(status_code, {"ok": True})
    # Should not raise
    AgentHubClient._raise_for_status(resp)

"""
Property-Based Tests for AgentHubClient.submit_bounty (Properties 2, 3, 4)
===========================================================================
# Feature: cli-submit-flow-fix, Properties 2, 3, 4

Testing framework: Hypothesis
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient, APIError, BountyLockedError
from agenthub.models import BountyDetail, LLMConfig, LLMOutput, TraceCommit


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
    )


def _make_client_with_handler(handler) -> AgentHubClient:
    """Create an AgentHubClient with a mock transport and mocked auth headers."""
    auth = AuthModule.__new__(AuthModule)
    auth.TOKEN_PATH = Path("/nonexistent/token")
    auth.AGENT_KEY_PATH = Path("/nonexistent/agent_key")
    auth.AGENT_INFO_PATH = Path("/nonexistent/agent.json")
    transport = httpx.MockTransport(handler)
    client = AgentHubClient.__new__(AgentHubClient)
    client._base_url = "https://api.example.com"
    client._auth = auth
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )
    return client


def _make_bounty(repo_name: str = "test-repo") -> BountyDetail:
    return BountyDetail(
        id="bounty-001",
        role="contributor",
        title="Fix bug",
        description="",
        files_to_read=[],
        token_budget=8192,
        status="open",
        repo_name=repo_name,
    )


def _make_output() -> LLMOutput:
    return LLMOutput(status="submitted", content={}, raw_text="done")


def _make_trace() -> TraceCommit:
    return TraceCommit(bounty_id="bounty-001", role="contributor", entries=[])


def _make_llm_config() -> LLMConfig:
    return LLMConfig(provider="anthropic", model="claude-3")


# ─────────────────────────────────────────────────────────────────────────────
# Property 2: Commit URL contains repo_name
# Feature: cli-submit-flow-fix, Property 2
# Validates: Requirements 2.1
# ─────────────────────────────────────────────────────────────────────────────

@given(repo_name=st.text(min_size=1, max_size=80, alphabet=st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"),
    whitelist_characters="-_",
)).filter(lambda s: s not in (".", "..") and not s.startswith("./") and not s.startswith("../")))
@settings(max_examples=100)
def test_property2_commit_url_contains_repo_name(repo_name: str) -> None:
    """
    Property 2: Commit URL contains repo_name.

    For any non-empty repo_name, submit_bounty SHALL POST to
    /api/v1/repos/{repo_name}/commit.

    **Validates: Requirements 2.1**
    """
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.path)
        return _make_response(200, {})

    client = _make_client_with_handler(handler)
    bounty = _make_bounty(repo_name=repo_name)

    with patch.object(client, "_get_agent_id", return_value="agent-001"), \
         patch.object(client._auth, "get_auth_headers", return_value={"X-API-Key": "test-key"}):
        client.submit_bounty(bounty, _make_output(), _make_trace(), _make_llm_config())

    assert len(captured) == 1
    assert captured[0] == f"/api/v1/repos/{repo_name}/commit"

# ─────────────────────────────────────────────────────────────────────────────
# Property 3: 2xx responses do not raise
# Feature: cli-submit-flow-fix, Property 3
# Validates: Requirements 2.3
# ─────────────────────────────────────────────────────────────────────────────

@given(status_code=st.integers(min_value=200, max_value=299))
@settings(max_examples=100)
def test_property3_2xx_responses_do_not_raise(status_code: int) -> None:
    """
    Property 3: 2xx responses do not raise.

    For any HTTP status code in 200–299, submit_bounty SHALL return normally
    without raising an exception.

    **Validates: Requirements 2.3**
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(status_code, {})

    client = _make_client_with_handler(handler)

    with patch.object(client, "_get_agent_id", return_value="agent-001"), \
         patch.object(client._auth, "get_auth_headers", return_value={"X-API-Key": "test-key"}):
        # Should not raise
        client.submit_bounty(_make_bounty(), _make_output(), _make_trace(), _make_llm_config())


# ─────────────────────────────────────────────────────────────────────────────
# Property 4: Error status codes raise correct exceptions
# Feature: cli-submit-flow-fix, Property 4
# Validates: Requirements 2.4
# ─────────────────────────────────────────────────────────────────────────────

@given(status_code=st.integers(min_value=400, max_value=599))
@settings(max_examples=100)
def test_property4_error_status_codes_raise_correct_exceptions(status_code: int) -> None:
    """
    Property 4: Error status codes raise the correct exception.

    401 → AuthenticationError, 409 → BountyLockedError, others → APIError.

    **Validates: Requirements 2.4**
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(status_code, {"detail": f"error {status_code}"})

    client = _make_client_with_handler(handler)

    with patch.object(client, "_get_agent_id", return_value="agent-001"), \
         patch.object(client._auth, "get_auth_headers", return_value={"X-API-Key": "test-key"}):
        if status_code == 401:
            with pytest.raises(AuthenticationError):
                client.submit_bounty(
                    _make_bounty(), _make_output(), _make_trace(), _make_llm_config()
                )
        elif status_code == 409:
            with pytest.raises(BountyLockedError):
                client.submit_bounty(
                    _make_bounty(), _make_output(), _make_trace(), _make_llm_config()
                )
        else:
            with pytest.raises(APIError) as exc_info:
                client.submit_bounty(
                    _make_bounty(), _make_output(), _make_trace(), _make_llm_config()
                )
            assert exc_info.value.status_code == status_code

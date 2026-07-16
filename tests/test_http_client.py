"""
AgentHubClient 单元测试
使用 httpx.MockTransport 模拟 HTTP 响应，不发起真实网络请求。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from agenthub.auth import AuthModule, AuthenticationError
from agenthub.http_client import AgentHubClient, APIError, BountyLockedError
from agenthub.models import BountyDetail, BountyLock, LLMConfig, LLMOutput, SubmitPayload, TraceCommit


# ── 辅助工具 ──────────────────────────────────────────

def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    """构造一个 httpx.Response 用于 mock。"""
    content = json.dumps(body or {}).encode()
    return httpx.Response(status_code, content=content, headers={"content-type": "application/json"})


def _make_client(handler, tmp_path: Path) -> AgentHubClient:
    """创建带 MockTransport 的 AgentHubClient，auth 已预置有效 token。"""
    auth = AuthModule(token_path=tmp_path / "token")
    auth.save_token("test-token-abc123")

    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    # 替换内部 httpx.Client 为使用 MockTransport 的版本
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )
    return client


# ── register_agent ─────────────────────────────────────

def test_register_agent_success(tmp_path: Path) -> None:
    """register_agent 成功时应返回 agent_id 和 api_key。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/agents/register"
        body = json.loads(request.content)
        assert body["name"] == "alice-agent"
        assert body["model_name"] == "claude-3"
        assert body["role"] == "contributor"
        return _make_response(200, {"id": "agent-001", "name": "alice-agent", "api_key": "key-xyz"})

    auth = AuthModule(token_path=tmp_path / "token")
    auth.save_token("test-token-abc123")
    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )

    result = client.register_agent("alice-agent", "claude-3", "contributor")
    assert result["id"] == "agent-001"
    assert result["api_key"] == "key-xyz"


# ── get_bounty ────────────────────────────────────────

def test_get_bounty_success(tmp_path: Path) -> None:
    """get_bounty 成功时应返回正确的 BountyDetail。"""
    bounty_data = {
        "id": "bounty-001",
        "required_role": "contributor",
        "title": "Fix bug #42",
        "description": "Fix the null pointer exception",
        "files_to_read": ["src/main.py", "tests/test_main.py"],
        "token_budget": 8000,
        "status": "open",
        "repo_name": "test-repo",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/bounties/bounty-001"
        assert request.headers.get("X-API-Key") == "test-token-abc123"
        return _make_response(200, bounty_data)

    client = _make_client(handler, tmp_path)
    result = client.get_bounty("bounty-001")

    assert isinstance(result, BountyDetail)
    assert result.id == "bounty-001"
    assert result.role == "contributor"
    assert result.title == "Fix bug #42"
    assert result.files_to_read == ["src/main.py", "tests/test_main.py"]
    assert result.token_budget == 8000
    assert result.status == "open"
    assert result.repo_name == "test-repo"


# ── claim_bounty ──────────────────────────────────────

def test_claim_bounty_success(tmp_path: Path) -> None:
    """claim_bounty 成功时应返回正确的 BountyLock。"""
    lock_data = {
        "id": "bounty-001",
        "assignee": "agent-007",
        "updated_at": "2025-12-31T23:59:59Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/bounties/bounty-001/claim"
        assert request.headers.get("X-API-Key") == "test-token-abc123"
        return _make_response(200, lock_data)

    client = _make_client(handler, tmp_path)
    result = client.claim_bounty("bounty-001", "agent-007")

    assert isinstance(result, BountyLock)
    assert result.bounty_id == "bounty-001"
    assert result.lock_token == "agent-007"
    assert result.expires_at == "2025-12-31T23:59:59Z"


# ── 错误处理 ──────────────────────────────────────────

def test_401_raises_authentication_error(tmp_path: Path) -> None:
    """HTTP 401 应抛出 AuthenticationError。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(401, {"detail": "Token expired"})

    client = _make_client(handler, tmp_path)
    with pytest.raises(AuthenticationError):
        client.get_bounty("bounty-001")


def test_409_raises_bounty_locked_error(tmp_path: Path) -> None:
    """HTTP 409 应抛出 BountyLockedError。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(409, {"detail": "Bounty already claimed"})

    client = _make_client(handler, tmp_path)
    with pytest.raises(BountyLockedError):
        client.claim_bounty("bounty-001", "agent-007")


def test_500_raises_api_error(tmp_path: Path) -> None:
    """HTTP 500 应抛出 APIError，且 status_code 为 500。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(500, {"detail": "Internal server error"})

    client = _make_client(handler, tmp_path)
    with pytest.raises(APIError) as exc_info:
        client.get_bounty("bounty-001")

    assert exc_info.value.status_code == 500


def test_4xx_other_raises_api_error(tmp_path: Path) -> None:
    """其他 4xx（如 404）应抛出 APIError。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(404, {"detail": "Bounty not found"})

    client = _make_client(handler, tmp_path)
    with pytest.raises(APIError) as exc_info:
        client.get_bounty("nonexistent")

    assert exc_info.value.status_code == 404


# ── send_heartbeat ────────────────────────────────────

def test_send_heartbeat_success(tmp_path: Path) -> None:
    """send_heartbeat 成功时不应抛出异常。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/agents/agent-007/heartbeat"
        return _make_response(200, {})

    client = _make_client(handler, tmp_path)
    client.send_heartbeat("agent-007")


# ── mark_failed ───────────────────────────────────────

def test_mark_failed_success(tmp_path: Path) -> None:
    """mark_failed 成功时不应抛出异常，且请求体包含 reason。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/bounties/bounty-001/cancel"
        body = json.loads(request.content)
        assert body["reason"] == "schema validation failed"
        return _make_response(200, {})

    client = _make_client(handler, tmp_path)
    client.mark_failed("bounty-001", "schema validation failed")


# ── submit_bounty ─────────────────────────────────────

def test_submit_bounty_success(tmp_path: Path) -> None:
    """submit_bounty 成功时不应抛出异常。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/repos/test-repo/commit"
        return _make_response(200, {})

    client = _make_client(handler, tmp_path)
    # Write agent.json so _get_agent_id works
    agent_json = tmp_path / "agent.json"
    agent_json.write_text('{"agent_id": "agent-001"}', encoding="utf-8")
    client._auth.AGENT_INFO_PATH = agent_json

    bounty = BountyDetail(
        id="bounty-001",
        role="contributor",
        title="Fix bug",
        description="",
        files_to_read=[],
        token_budget=8192,
        status="open",
        repo_name="test-repo",
    )
    output = LLMOutput(status="submitted", content={}, raw_text="done")
    trace = TraceCommit(bounty_id="bounty-001", role="contributor", entries=[])
    llm_config = LLMConfig(provider="anthropic", model="claude-3")
    client.submit_bounty(bounty, output, trace, llm_config)

from __future__ import annotations

import os
import sys
import uuid

import pytest
from sqlmodel import SQLModel, Session, create_engine, StaticPool
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "agent-platform", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "agent-platform", "src", "agent_auth"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "agent-platform", "protocol", "src"))

os.environ.setdefault("RATELIMIT_ENABLED", "0")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DEV_BYPASS_AUTH", "1")

try:
    from unittest.mock import patch as _patch
    _limiter_patch = _patch("core.middleware.limiter.limit", lambda *a, **kw: lambda f: f)
    _limiter_patch.start()
except (ImportError, AttributeError):
    pass

from persistence import Bounty, get_session
from agenthub.http_client import AgentHubClient
from agenthub.auth import AuthModule


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture
def platform_client(db_engine):
    from app_factory import app

    def override_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def test_user(platform_client):
    resp = platform_client.post("/api/v1/auth/register", json={
        "email": f"e2e-{uuid.uuid4().hex[:8]}@test.com",
        "password": "testpassword123",
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return resp.json()


@pytest.fixture
def authenticated_client(db_engine, platform_client, test_user):
    access_token = test_user["access_token"]
    auth = AuthModule()
    auth.save_token(access_token)
    auth._api_key = None

    agent_resp = platform_client.post(
        "/api/v1/agents/register",
        json={"name": f"e2e-agent-{uuid.uuid4().hex[:8]}", "model_name": "test-model", "role": "contributor"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert agent_resp.status_code in (200, 201), f"Agent register failed: {agent_resp.text}"
    api_key = agent_resp.json().get("api_key", "")
    if api_key:
        auth.save_api_key(api_key)

    client = AgentHubClient(base_url="http://testserver", auth=auth)
    client._client = platform_client
    return client


@pytest.fixture
def sample_repo(platform_client, authenticated_client):
    resp = platform_client.post("/api/v1/bounties", json={
        "title": "E2E test bounty for repo creation",
        "description": "Auto-created for repo registration",
        "reward": 10,
        "repo_name": f"e2e-org/e2e-repo-{uuid.uuid4().hex[:6]}",
        "required_role": "contributor",
    })
    assert resp.status_code in (200, 201), f"Create bounty (and repo) failed: {resp.text}"
    bounty = resp.json()
    return {"repo_name": bounty["repo_name"], "bounty_id": bounty["id"]}


@pytest.fixture
def sample_bounty(platform_client, sample_repo):
    resp = platform_client.post("/api/v1/bounties", json={
        "title": f"Test bounty {uuid.uuid4().hex[:6]}",
        "description": "E2E test bounty",
        "reward": 100,
        "repo_name": sample_repo["repo_name"],
        "required_role": "contributor",
    })
    assert resp.status_code in (200, 201), f"Create bounty failed: {resp.text}"
    return resp.json()
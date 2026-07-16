"""
Verification tests for cli-submit-flow-fix.

These tests CONFIRM the bugs have been FIXED:
- BountyDetail now has repo_name field
- get_bounty preserves repo_name
- submit_bounty uses the correct /repos/{repo_name}/commit endpoint
- ProcessManager passes correct arguments to submit_bounty
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agenthub.auth import AuthModule
from agenthub.http_client import AgentHubClient, build_commit_payload
from agenthub.models import (
    BountyDetail,
    LLMConfig,
    LLMOutput,
    SkillConfig,
    TraceCommit,
    TraceEntry,
    ToolCall,
    ToolResult,
    ValidationResult,
)
from agenthub.process_manager import ProcessManager


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
    )


def _make_client(handler, tmp_path: Path) -> AgentHubClient:
    auth = AuthModule(token_path=tmp_path / "token")
    auth.save_token("test-token-abc123")
    transport = httpx.MockTransport(handler)
    client = AgentHubClient(base_url="https://api.example.com", auth=auth)
    client._client = httpx.Client(
        base_url="https://api.example.com",
        transport=transport,
        timeout=30.0,
    )
    return client


def _make_bounty() -> BountyDetail:
    return BountyDetail(
        id="bounty-123",
        role="contributor",
        title="Test Bounty",
        description="Implement feature X",
        files_to_read=["src/main.py"],
        token_budget=4096,
        status="claimed",
        repo_name="test-repo",
    )


def _make_skill_config() -> SkillConfig:
    return SkillConfig(
        role="contributor",
        system_prompt_template="You are a contributor.",
        tool_whitelist=["read_file", "write_file"],
        path_rules=["src/**"],
        output_schema={
            "type": "object",
            "required": ["status", "summary"],
            "properties": {
                "status": {"type": "string"},
                "summary": {"type": "string"},
            },
        },
    )


# ── 1.1 BountyDetail has repo_name ──────────────────────────────────────────

def test_bounty_detail_has_repo_name_field():
    """BountyDetail now has repo_name field after fix."""
    bounty = BountyDetail(
        id="b1",
        role="contributor",
        title="T",
        description="D",
        files_to_read=[],
        token_budget=8192,
        status="open",
        repo_name="my-repo",
    )
    assert bounty.repo_name == "my-repo"


# ── 1.2 get_bounty preserves repo_name ──────────────────────────────────────

def test_get_bounty_preserves_repo_name(tmp_path: Path) -> None:
    """get_bounty now preserves repo_name from the JSON response."""
    bounty_data = {
        "id": "b1",
        "required_role": "contributor",
        "title": "T",
        "description": "D",
        "files_to_read": [],
        "token_budget": 8192,
        "status": "open",
        "repo_name": "my-repo",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _make_response(200, bounty_data)

    client = _make_client(handler, tmp_path)
    result = client.get_bounty("b1")

    assert hasattr(result, "repo_name")
    assert result.repo_name == "my-repo"


# ── 1.3 submit_bounty uses correct endpoint ─────────────────────────────────

def test_submit_bounty_uses_commit_endpoint(tmp_path: Path) -> None:
    """submit_bounty now POSTs to /api/v1/repos/{repo_name}/commit."""
    captured_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_paths.append(request.url.path)
        return _make_response(200, {"success": True})

    client = _make_client(handler, tmp_path)
    bounty = _make_bounty()
    output = LLMOutput(status="submitted", content={"status": "submitted"}, raw_text="done")
    trace = TraceCommit(bounty_id="bounty-123", role="contributor", entries=[])
    llm_config = LLMConfig(provider="anthropic", model="claude-3", api_key="test-key")

    # Save agent info so _get_agent_id works
    from agenthub.auth import AuthModule
    agent_info_path = AuthModule.AGENT_INFO_PATH
    agent_info_path.parent.mkdir(parents=True, exist_ok=True)
    agent_info_path.write_text(json.dumps({"agent_id": "agent-1", "name": "test", "role": "contributor"}), encoding="utf-8")

    client.submit_bounty(bounty=bounty, output=output, trace=trace, llm_config=llm_config)

    assert len(captured_paths) == 1
    assert captured_paths[0] == "/api/v1/repos/test-repo/commit"

    # Cleanup
    if agent_info_path.exists():
        agent_info_path.unlink()


# ── 1.4 ProcessManager passes correct arguments ─────────────────────────────

def test_process_manager_passes_correct_args_to_submit_bounty() -> None:
    """ProcessManager._execute now passes BountyDetail, LLMOutput, TraceCommit, LLMConfig."""
    bounty = _make_bounty()
    skill_config = _make_skill_config()
    llm_output = LLMOutput(
        status="submitted",
        content={"status": "submitted", "summary": "Done"},
        raw_text="done",
    )
    trace_commit = TraceCommit(bounty_id="bounty-123", role="contributor", entries=[])

    client = MagicMock()
    client.get_bounty.return_value = bounty

    auth = MagicMock()
    skill_loader = MagicMock()
    skill_loader.load.return_value = skill_config
    context_builder = MagicMock()
    context_builder.build.return_value = MagicMock()
    schema_validator = MagicMock()
    schema_validator.validate.return_value = ValidationResult(ok=True, attempt=0)

    trace_writer_mock = MagicMock()
    trace_writer_mock.to_trace_commit.return_value = trace_commit
    llm_runner_mock = MagicMock()
    llm_runner_mock.run.return_value = llm_output

    pm = ProcessManager(
        client=client,
        auth=auth,
        skill_loader=skill_loader,
        context_builder=context_builder,
        schema_validator=schema_validator,
        bounty_id="bounty-123",
        heartbeat_interval=9999,
    )

    with patch("agenthub.process_manager.load_config") as mock_config, \
         patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
         patch("agenthub.process_manager.ToolInterceptor"), \
         patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
        mock_config.return_value = MagicMock(llm=LLMConfig(provider="anthropic", model="claude-3", api_key="test"))
        pm.run()

    client.submit_bounty.assert_called_once()
    call_kwargs = client.submit_bounty.call_args.kwargs
    assert call_kwargs["bounty"] == bounty
    assert call_kwargs["output"] == llm_output
    assert call_kwargs["trace"] == trace_commit
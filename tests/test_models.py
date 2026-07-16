"""Unit tests for core data models."""
from agenthub.models import (
    LLMConfig,
    AppConfig,
    SkillConfig,
    BountyDetail,
    BountyLock,
    FileContent,
    Context,
    ToolCall,
    ToolResult,
    LLMOutput,
    ValidationResult,
    TraceEntry,
    TraceCommit,
    SubmitPayload,
)


def test_llm_config_defaults():
    cfg = LLMConfig(provider="claude-code", model="claude-opus-4-5")
    assert cfg.api_key is None


def test_app_config():
    llm = LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20241022", api_key="sk-test")
    app = AppConfig(api_base_url="https://api.example.com", llm=llm)
    assert app.api_base_url == "https://api.example.com"
    assert app.llm is llm


def test_skill_config():
    sc = SkillConfig(
        role="contributor",
        system_prompt_template="You are a contributor: {{ bounty.description }}",
        tool_whitelist=["read_file", "write_file"],
        path_rules=["src/**", "tests/**"],
        output_schema={"type": "object"},
    )
    assert sc.role == "contributor"
    assert len(sc.tool_whitelist) == 2


def test_bounty_detail():
    b = BountyDetail(
        id="b-001",
        role="contributor",
        title="Fix bug",
        description="Fix the login bug",
        files_to_read=["src/auth.py"],
        token_budget=4096,
        status="open",
        repo_name="test-repo",
    )
    assert b.id == "b-001"
    assert b.token_budget == 4096


def test_bounty_lock():
    lock = BountyLock(
        bounty_id="b-001",
        lock_token="tok-abc",
        expires_at="2025-01-01T00:00:00Z",
    )
    assert lock.bounty_id == "b-001"


def test_file_content_defaults():
    fc = FileContent(path="src/main.py", content="print('hello')")
    assert fc.missing is False

    fc_missing = FileContent(path="src/missing.py", content=None, missing=True)
    assert fc_missing.missing is True
    assert fc_missing.content is None


def test_context():
    bounty = BountyDetail(
        id="b-001", role="contributor", title="T", description="D",
        files_to_read=[], token_budget=1000, status="open",
        repo_name="test-repo",
    )
    ctx = Context(
        system_prompt="You are an agent.",
        bounty=bounty,
        files=[],
        token_budget=1000,
    )
    assert ctx.system_prompt == "You are an agent."
    assert ctx.bounty is bounty


def test_tool_call_and_result():
    tc = ToolCall(id="tc-1", name="read_file", args={"path": "src/main.py"})
    tr = ToolResult(tool_call_id="tc-1", output="file content", allowed=True)
    assert tc.name == "read_file"
    assert tr.allowed is True

    denied = ToolResult(tool_call_id="tc-2", output="permission_denied", allowed=False)
    assert denied.allowed is False


def test_llm_output():
    out = LLMOutput(status="submitted", content={"summary": "done"}, raw_text="raw")
    assert out.status == "submitted"


def test_validation_result_defaults():
    vr = ValidationResult(ok=True)
    assert vr.errors == []
    assert vr.attempt == 0

    vr_fail = ValidationResult(ok=False, errors=["missing field"], attempt=1)
    assert len(vr_fail.errors) == 1


def test_trace_entry_and_commit():
    tc = ToolCall(id="tc-1", name="read_file", args={})
    tr = ToolResult(tool_call_id="tc-1", output="content", allowed=True)
    entry = TraceEntry(tool_call=tc, result=tr, timestamp="2025-01-01T00:00:00Z")

    commit = TraceCommit(bounty_id="b-001", role="contributor", entries=[entry])
    assert len(commit.entries) == 1
    assert commit.entries[0].tool_call.id == "tc-1"


def test_submit_payload():
    tc = ToolCall(id="tc-1", name="write_file", args={})
    tr = ToolResult(tool_call_id="tc-1", output="ok", allowed=True)
    entry = TraceEntry(tool_call=tc, result=tr, timestamp="2025-01-01T00:00:00Z")
    commit = TraceCommit(bounty_id="b-001", role="contributor", entries=[entry])

    payload = SubmitPayload(output={"status": "submitted", "summary": "done"}, trace=commit)
    assert payload.output["status"] == "submitted"
    assert payload.trace is commit

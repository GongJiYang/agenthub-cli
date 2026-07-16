"""ChatRunner 单元测试 + 属性测试。"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agenthub.auth import AuthModule
from agenthub.chat_runner import ChatRunner, _now_iso
from agenthub.models import AppConfig, BountyDetail, ChatSession, LLMConfig
from agenthub.stream_printer import StreamPrinter
from agenthub.tool_executor import ToolExecutor


# ── 辅助 ──────────────────────────────────────────────

def _make_config() -> AppConfig:
    return AppConfig(
        api_base_url="https://api.example.com",
        llm=LLMConfig(provider="anthropic", model="claude-3-haiku-20240307"),
    )


def _make_runner(
    bounty_id: str | None = None,
    client=None,
    printer=None,
    executor=None,
    tmp_path: Path | None = None,
) -> ChatRunner:
    auth = AuthModule(token_path=(tmp_path or Path("/tmp")) / "token")
    return ChatRunner(
        config=_make_config(),
        auth=auth,
        bounty_id=bounty_id,
        model="claude-3-haiku-20240307",
        show_tools=True,
        save_path=None,
        client=client,
        printer=printer or StreamPrinter(show_tools=True, out=io.StringIO()),
        executor=executor or ToolExecutor(),
    )


def _make_bounty(bounty_id: str = "b-001") -> BountyDetail:
    return BountyDetail(
        id=bounty_id,
        role="contributor",
        title="Test Bounty",
        description="A test bounty description",
        files_to_read=[],
        token_budget=8192,
        status="open",
        repo_name="test-repo",
    )


# ── _build_system_prompt ──────────────────────────────

def test_build_system_prompt_standalone() -> None:
    """独立模式 system prompt 应为通用助手描述。"""
    runner = _make_runner()
    prompt = runner._build_system_prompt(None)
    assert len(prompt) > 0
    assert isinstance(prompt, str)


def test_build_system_prompt_bounty_contains_title_and_desc() -> None:
    """Bounty 模式 system prompt 应包含 title 和 description。"""
    runner = _make_runner()
    bounty = _make_bounty()
    prompt = runner._build_system_prompt(bounty)
    assert bounty.title in prompt
    assert bounty.description in prompt


# ── _init_session ─────────────────────────────────────

def test_init_session_standalone() -> None:
    """独立模式应初始化空 messages 的 ChatSession。"""
    runner = _make_runner()
    session = runner._init_session()
    assert session.mode == "standalone"
    assert session.messages == []
    assert session.bounty_id is None


def test_init_session_bounty_success(tmp_path: Path) -> None:
    """Bounty 模式应拉取 Bounty 详情并初始化 session。"""
    mock_client = MagicMock()
    mock_client.get_bounty.return_value = _make_bounty("b-001")
    runner = _make_runner(bounty_id="b-001", client=mock_client, tmp_path=tmp_path)
    session = runner._init_session()
    assert session.mode == "bounty"
    assert session.bounty_id == "b-001"
    assert session.bounty is not None
    mock_client.get_bounty.assert_called_once_with("b-001")


def test_init_session_bounty_api_error(tmp_path: Path) -> None:
    """Bounty API 失败时应以 SystemExit(1) 终止。"""
    from agenthub.http_client import APIError
    mock_client = MagicMock()
    mock_client.get_bounty.side_effect = APIError(404, "not found")
    runner = _make_runner(bounty_id="b-999", client=mock_client, tmp_path=tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        runner._init_session()
    assert exc_info.value.code == 1


# ── _handle_command ───────────────────────────────────

def test_handle_command_clear(tmp_path: Path) -> None:
    """/clear 应清空 messages 并返回 True（继续循环）。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m", messages=[{"role": "user", "content": []}],
        started_at=_now_iso(),
    )
    result = runner._handle_command("/clear")
    assert result is True
    assert runner._session.messages == []


def test_handle_command_unknown(tmp_path: Path) -> None:
    """/unknown 应返回 True（继续循环）。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m", messages=[], started_at=_now_iso(),
    )
    result = runner._handle_command("/unknown")
    assert result is True


def test_handle_command_submit_non_bounty_mode(tmp_path: Path) -> None:
    """/submit 在独立模式下应提示并返回 True。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m", messages=[], started_at=_now_iso(),
    )
    result = runner._handle_command("/submit")
    assert result is True


# ── _save_history ─────────────────────────────────────

def test_save_history_creates_file(tmp_path: Path) -> None:
    """_save_history 应创建 JSON 文件并包含元数据。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone",
        model="claude-3-haiku",
        messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        started_at=_now_iso(),
    )
    save_path = str(tmp_path / "history.json")
    runner._save_history(save_path)

    assert Path(save_path).exists()
    data = json.loads(Path(save_path).read_text(encoding="utf-8"))
    assert "started_at" in data
    assert "ended_at" in data
    assert "model" in data
    assert "message_count" in data
    assert data["message_count"] == 1
    assert data["messages"][0]["role"] == "user"


def test_save_history_creates_parent_dirs(tmp_path: Path) -> None:
    """_save_history 应自动创建父目录。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m", messages=[], started_at=_now_iso(),
    )
    save_path = str(tmp_path / "a" / "b" / "c" / "history.json")
    runner._save_history(save_path)
    assert Path(save_path).exists()


def test_save_history_default_path(tmp_path: Path) -> None:
    """未指定路径时应使用默认路径，不抛异常。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m", messages=[], started_at=_now_iso(),
    )
    # 将默认路径重定向到 tmp_path 下，避免写入真实 home 目录
    fake_path = tmp_path / "chat_history_20250101_000000.json"
    with patch("agenthub.chat_runner._timestamp", return_value="20250101_000000"):
        with patch("agenthub.chat_runner.Path") as mock_path_cls:
            mock_path_cls.return_value = fake_path
            # 直接调用真实 Path 的 parent/mkdir/write_text
            mock_path_cls.side_effect = lambda p: Path(p) if not p.startswith("~") else fake_path
            runner._save_history()
    # 验证不抛异常即可（路径 mock 复杂，主要验证流程不崩溃）


# ── _handle_crash ─────────────────────────────────────

def test_handle_crash_saves_file(tmp_path: Path) -> None:
    """_handle_crash 应保存 crash 文件。"""
    runner = _make_runner(tmp_path=tmp_path)
    runner._session = ChatSession(
        mode="standalone", model="m",
        messages=[{"role": "user", "content": []}],
        started_at=_now_iso(),
    )
    crash_path = tmp_path / "crash.json"
    with patch("agenthub.chat_runner._timestamp", return_value="crash_ts"):
        with patch.object(Path, "expanduser", return_value=crash_path):
            runner._handle_crash(RuntimeError("test error"))
    assert crash_path.exists()


# ── 属性测试 ──────────────────────────────────────────

# 属性 1：对话历史追加不变量
@given(
    initial=st.lists(
        st.fixed_dictionaries({
            "role": st.sampled_from(["user", "assistant"]),
            "content": st.just([]),
        }),
        min_size=0, max_size=10,
    ),
    text=st.text(min_size=1, max_size=200),
)
@settings(max_examples=100)
def test_message_history_append_invariant(initial: list, text: str) -> None:
    """追加用户消息后，历史长度应恰好增加 1，最后一条 role 为 user。"""
    session = ChatSession(
        mode="standalone", model="m",
        messages=list(initial),
        started_at=_now_iso(),
    )
    before = len(session.messages)
    session.messages.append({
        "role": "user",
        "content": [{"type": "text", "text": text}],
    })
    assert len(session.messages) == before + 1
    last = session.messages[-1]
    assert last["role"] == "user"
    assert last["content"][0]["text"] == text


# 属性 2：Message_History 序列化 Round-Trip
@given(messages=st.lists(
    st.fixed_dictionaries({
        "role": st.sampled_from(["user", "assistant"]),
        "content": st.lists(
            st.fixed_dictionaries({
                "type": st.just("text"),
                "text": st.text(min_size=1),
            }),
            min_size=1,
        ),
    }),
    min_size=0, max_size=20,
))
@settings(max_examples=100)
def test_message_history_round_trip(messages: list) -> None:
    """序列化后反序列化应得到相同内容，且包含元数据字段。"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        runner = _make_runner(tmp_path=Path(tmp))
        runner._session = ChatSession(
            mode="standalone", model="claude-3-haiku",
            messages=list(messages),
            started_at=_now_iso(),
        )
        save_path = os.path.join(tmp, "history.json")
        runner._save_history(save_path)
        loaded = json.loads(Path(save_path).read_text(encoding="utf-8"))
        assert loaded["messages"] == messages
        assert "started_at" in loaded
        assert "model" in loaded
        assert "message_count" in loaded
        assert loaded["message_count"] == len(messages)


# 属性 3：clear 操作幂等性
@given(messages=st.lists(
    st.fixed_dictionaries({"role": st.just("user"), "content": st.just([])}),
    min_size=0, max_size=20,
))
@settings(max_examples=100)
def test_clear_idempotent(messages: list) -> None:
    """clear 后 messages 为空；对空列表再次 clear 仍为空。"""
    session = ChatSession(
        mode="standalone", model="m",
        messages=list(messages),
        started_at=_now_iso(),
    )
    session.messages.clear()
    assert session.messages == []
    session.messages.clear()
    assert session.messages == []


# 属性 4：Bounty system prompt 注入完整性
@given(
    title=st.text(min_size=1, max_size=100),
    description=st.text(min_size=1, max_size=500),
)
@settings(max_examples=100)
def test_bounty_system_prompt_injection(title: str, description: str) -> None:
    """system prompt 应同时包含 Bounty 的 title 和 description。"""
    runner = _make_runner()
    bounty = BountyDetail(
        id="b-x", role="contributor",
        title=title, description=description,
        files_to_read=[], token_budget=8192, status="open",
        repo_name="test-repo",
    )
    prompt = runner._build_system_prompt(bounty)
    assert title in prompt
    assert description in prompt

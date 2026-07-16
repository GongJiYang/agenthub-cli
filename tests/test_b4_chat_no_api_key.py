"""
B4 Bug Condition Exploration Test — chat 命令 api_key 为 None 时无友好提示

Bug Condition:
  isBugCondition_B4(X) where:
    X.config.llm.api_key = None OR X.config.llm.api_key = ""

Expected (correct) behavior:
  _call_llm_streaming SHOULD print a friendly message containing "api_key"
  and return WITHOUT raising an SDK internal exception.

This test asserts the CORRECT behavior. It will FAIL on unfixed code where
None is passed directly to anthropic.Anthropic(api_key=None), causing
the SDK to raise an internal AuthenticationError or TypeError.

Validates: Requirements 1.4
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenthub.auth import AuthModule
from agenthub.chat_runner import ChatRunner
from agenthub.models import AppConfig, ChatSession, LLMConfig
from agenthub.stream_printer import StreamPrinter


def _make_runner_no_api_key(tmp_path: Path, api_key=None) -> ChatRunner:
    """Create a ChatRunner with no/empty api_key."""
    config = AppConfig(
        api_base_url="https://api.example.com",
        llm=LLMConfig(provider="anthropic", model="claude-3-haiku-20240307", api_key=api_key),
    )
    auth = AuthModule(token_path=tmp_path / "token")
    out = io.StringIO()
    return ChatRunner(
        config=config,
        auth=auth,
        bounty_id=None,
        model="claude-3-haiku-20240307",
        show_tools=False,
        save_path=None,
        printer=StreamPrinter(show_tools=False, out=out),
    )


def test_call_llm_streaming_with_none_api_key_does_not_raise_sdk_exception(tmp_path: Path) -> None:
    """
    B4: _call_llm_streaming with api_key=None MUST NOT raise SDK internal exception.

    On unfixed code: anthropic.Anthropic(api_key=None) raises SDK AuthenticationError.
    On fixed code: friendly message is printed and function returns early.
    """
    runner = _make_runner_no_api_key(tmp_path, api_key=None)
    runner._session = ChatSession(
        mode="standalone",
        model="claude-3-haiku-20240307",
        messages=[],
        started_at="2025-01-01T00:00:00Z",
    )

    # Should NOT raise any exception
    try:
        runner._call_llm_streaming("test system prompt")
    except Exception as e:
        pytest.fail(
            f"BUG B4: _call_llm_streaming raised {type(e).__name__}: {e} "
            "when api_key is None. Should print friendly message and return."
        )


def test_call_llm_streaming_with_empty_api_key_does_not_raise_sdk_exception(tmp_path: Path) -> None:
    """
    B4: _call_llm_streaming with api_key="" MUST NOT raise SDK internal exception.
    """
    runner = _make_runner_no_api_key(tmp_path, api_key="")
    runner._session = ChatSession(
        mode="standalone",
        model="claude-3-haiku-20240307",
        messages=[],
        started_at="2025-01-01T00:00:00Z",
    )

    try:
        runner._call_llm_streaming("test system prompt")
    except Exception as e:
        pytest.fail(
            f"BUG B4: _call_llm_streaming raised {type(e).__name__}: {e} "
            "when api_key is empty string. Should print friendly message and return."
        )


def test_call_llm_streaming_prints_friendly_message_when_no_api_key(tmp_path: Path, capsys) -> None:
    """
    B4: When api_key is None, _call_llm_streaming MUST print a message
    containing 'api_key' keyword.
    """
    runner = _make_runner_no_api_key(tmp_path, api_key=None)
    runner._session = ChatSession(
        mode="standalone",
        model="claude-3-haiku-20240307",
        messages=[],
        started_at="2025-01-01T00:00:00Z",
    )

    runner._call_llm_streaming("test system prompt")

    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert "api_key" in output.lower() or "api key" in output.lower(), (
        f"BUG B4: No friendly message containing 'api_key' was printed. "
        f"Output was: {output!r}. "
        "When api_key is None, a friendly message should guide the user."
    )


def test_call_llm_streaming_checks_api_key_before_sdk_init(tmp_path: Path) -> None:
    """
    B4: _call_llm_streaming MUST check api_key BEFORE initializing the Anthropic SDK.

    Verifies the fix is in place by inspecting the source code.
    """
    import inspect
    from agenthub.chat_runner import ChatRunner

    source = inspect.getsource(ChatRunner._call_llm_streaming)

    # The fix requires checking api_key before creating anthropic.Anthropic(...)
    assert "if not api_key" in source or "if api_key is None" in source or "if not api_key:" in source, (
        "BUG B4: _call_llm_streaming does not check api_key before SDK initialization. "
        "None will be passed to anthropic.Anthropic(api_key=None), causing SDK exception."
    )

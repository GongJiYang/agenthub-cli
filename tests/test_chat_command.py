"""chat 子命令 CLI 测试。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agenthub.main import cli


# ── --help ────────────────────────────────────────────

def test_chat_help() -> None:
    """agenthub chat --help 应正常输出帮助信息。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--bounty" in result.output
    assert "--model" in result.output
    assert "--show-tools" in result.output
    assert "--save-history" in result.output


# ── 独立模式 ──────────────────────────────────────────

def test_chat_standalone_mode(tmp_path: Path) -> None:
    """不传 --bounty 时应进入独立对话模式，不检查 token。"""
    mock_runner = MagicMock()
    mock_runner.run.return_value = 0

    with patch("agenthub.commands.chat.ChatRunner", return_value=mock_runner) as mock_cls:
        with patch("agenthub.commands.chat.load_config"):
            runner = CliRunner()
            result = runner.invoke(cli, ["chat"])

    mock_cls.assert_called_once()
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["bounty_id"] is None
    mock_runner.run.assert_called_once()


# ── Bounty 模式认证失败 ───────────────────────────────

def test_chat_bounty_auth_failure(tmp_path: Path) -> None:
    """--bounty 指定但 token 不存在时应以退出码 1 终止。"""
    from agenthub.auth import AuthenticationError

    with patch("agenthub.commands.chat.AuthModule") as mock_auth_cls:
        mock_auth = MagicMock()
        mock_auth.load_token.side_effect = AuthenticationError("no token")
        mock_auth_cls.return_value = mock_auth

        with patch("agenthub.commands.chat.load_config"):
            runner = CliRunner()
            result = runner.invoke(cli, ["chat", "--bounty", "b-001"])

    assert result.exit_code == 1
    assert "认证失败" in result.output


# ── Bounty 模式认证成功 ───────────────────────────────

def test_chat_bounty_mode_success(tmp_path: Path) -> None:
    """--bounty 指定且 token 存在时应进入 Bounty 模式。"""
    mock_runner = MagicMock()
    mock_runner.run.return_value = 0

    with patch("agenthub.commands.chat.ChatRunner", return_value=mock_runner) as mock_cls:
        with patch("agenthub.commands.chat.AuthModule") as mock_auth_cls:
            mock_auth = MagicMock()
            mock_auth.load_token.return_value = "valid-token"
            mock_auth_cls.return_value = mock_auth

            with patch("agenthub.commands.chat.load_config"):
                runner = CliRunner()
                result = runner.invoke(cli, ["chat", "--bounty", "b-001"])

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["bounty_id"] == "b-001"
    mock_runner.run.assert_called_once()


# ── 参数传递 ──────────────────────────────────────────

def test_chat_model_param() -> None:
    """--model 参数应正确传递给 ChatRunner。"""
    mock_runner = MagicMock()
    mock_runner.run.return_value = 0

    with patch("agenthub.commands.chat.ChatRunner", return_value=mock_runner) as mock_cls:
        with patch("agenthub.commands.chat.load_config"):
            runner = CliRunner()
            runner.invoke(cli, ["chat", "--model", "claude-3-opus-20240229"])

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["model"] == "claude-3-opus-20240229"


def test_chat_no_show_tools() -> None:
    """--no-show-tools 应将 show_tools=False 传给 ChatRunner。"""
    mock_runner = MagicMock()
    mock_runner.run.return_value = 0

    with patch("agenthub.commands.chat.ChatRunner", return_value=mock_runner) as mock_cls:
        with patch("agenthub.commands.chat.load_config"):
            runner = CliRunner()
            runner.invoke(cli, ["chat", "--no-show-tools"])

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["show_tools"] is False


def test_chat_save_history_param() -> None:
    """--save-history 参数应正确传递给 ChatRunner。"""
    mock_runner = MagicMock()
    mock_runner.run.return_value = 0

    with patch("agenthub.commands.chat.ChatRunner", return_value=mock_runner) as mock_cls:
        with patch("agenthub.commands.chat.load_config"):
            runner = CliRunner()
            runner.invoke(cli, ["chat", "--save-history", "/tmp/history.json"])

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["save_path"] == "/tmp/history.json"

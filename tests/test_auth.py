"""
单元测试：AuthModule（auth.py）
覆盖：save/load round-trip、文件不存在、过期 JWT、有效 JWT、get_auth_headers 格式
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from agenthub.auth import AuthModule, AuthenticationError


# ── 辅助函数 ──────────────────────────────────────────

def _make_jwt(exp: int) -> str:
    """构造一个最小 JWT（header.payload.signature），exp 可自定义。"""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "agent-1", "exp": exp}).encode()
    ).rstrip(b"=").decode()
    signature = "fakesig"
    return f"{header}.{payload}.{signature}"


# ── 测试：save / load round-trip ──────────────────────

def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    auth = AuthModule(token_path=token_file)

    token = "my-secret-passport-token"
    auth.save_token(token)
    assert auth.load_token() == token


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    token_file = tmp_path / "nested" / "dir" / "token"
    auth = AuthModule(token_path=token_file)

    auth.save_token("abc123")
    assert token_file.exists()
    assert token_file.read_text() == "abc123"


# ── 测试：文件不存在 ──────────────────────────────────

def test_load_raises_when_file_missing(tmp_path: Path) -> None:
    auth = AuthModule(token_path=tmp_path / "token")
    with pytest.raises(AuthenticationError):
        auth.load_token()


def test_load_raises_when_file_empty(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("   \n", encoding="utf-8")
    auth = AuthModule(token_path=token_file)
    with pytest.raises(AuthenticationError):
        auth.load_token()


# ── 测试：过期 JWT ────────────────────────────────────

def test_load_raises_for_expired_jwt(tmp_path: Path) -> None:
    expired_jwt = _make_jwt(exp=int(time.time()) - 3600)  # 1 小时前过期
    token_file = tmp_path / "token"
    token_file.write_text(expired_jwt, encoding="utf-8")

    auth = AuthModule(token_path=token_file)
    with pytest.raises(AuthenticationError, match="过期"):
        auth.load_token()


# ── 测试：有效 JWT ────────────────────────────────────

def test_load_returns_valid_jwt(tmp_path: Path) -> None:
    valid_jwt = _make_jwt(exp=int(time.time()) + 3600)  # 1 小时后过期
    token_file = tmp_path / "token"
    token_file.write_text(valid_jwt, encoding="utf-8")

    auth = AuthModule(token_path=token_file)
    assert auth.load_token() == valid_jwt


# ── 测试：非 JWT token 不做过期检测 ──────────────────

def test_load_non_jwt_token_passes_without_expiry_check(tmp_path: Path) -> None:
    opaque_token = "opaque-token-no-dots"
    token_file = tmp_path / "token"
    token_file.write_text(opaque_token, encoding="utf-8")

    auth = AuthModule(token_path=token_file)
    assert auth.load_token() == opaque_token


# ── 测试：get_auth_headers 格式 ───────────────────────

def test_get_auth_headers_format(tmp_path: Path) -> None:
    token = "test-token-value"
    token_file = tmp_path / "token"
    token_file.write_text(token, encoding="utf-8")

    auth = AuthModule(token_path=token_file)
    headers = auth.get_auth_headers()

    assert headers == {"X-API-Key": token}


def test_get_auth_headers_raises_when_no_token(tmp_path: Path) -> None:
    auth = AuthModule(token_path=tmp_path / "token")
    with pytest.raises(AuthenticationError):
        auth.get_auth_headers()


def test_get_auth_headers_with_valid_jwt(tmp_path: Path) -> None:
    valid_jwt = _make_jwt(exp=int(time.time()) + 7200)
    token_file = tmp_path / "token"
    token_file.write_text(valid_jwt, encoding="utf-8")

    auth = AuthModule(token_path=token_file)
    headers = auth.get_auth_headers()
    assert headers["Authorization"] == f"Bearer {valid_jwt}"

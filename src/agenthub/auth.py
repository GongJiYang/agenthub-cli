from __future__ import annotations

import base64
import json
import time
from pathlib import Path


class AuthenticationError(Exception):
    """Token 不存在、为空或已过期时抛出。"""


class AuthModule:
    TOKEN_PATH: Path = Path("~/.agenthub/token").expanduser()
    AGENT_KEY_PATH: Path = Path("~/.agenthub/agent_key").expanduser()
    AGENT_INFO_PATH: Path = Path("~/.agenthub/agent.json").expanduser()

    def __init__(self, token_path: Path | None = None) -> None:
        if token_path is not None:
            self.TOKEN_PATH = token_path

    # ── 公开接口 ──────────────────────────────────────

    def save_token(self, token: str) -> None:
        """将 JWT 写入 TOKEN_PATH，权限 0o600，目录 0o700。"""
        self._write_secure(self.TOKEN_PATH, token)

    def save_agent_key(self, api_key: str) -> None:
        """将 api_key 写入 AGENT_KEY_PATH，权限 0o600。"""
        self._write_secure(self.AGENT_KEY_PATH, api_key)

    def save_agent_info(self, agent_id: str, name: str, role: str) -> None:
        """将 agent 信息写入 AGENT_INFO_PATH（JSON）。"""
        import json as _json
        self.AGENT_INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.AGENT_INFO_PATH.write_text(
            _json.dumps({"agent_id": agent_id, "name": name, "role": role}),
            encoding="utf-8",
        )

    def load_token(self) -> str:
        """
        从 TOKEN_PATH 读取 token。
        - 文件不存在或内容为空 → AuthenticationError
        - 是 JWT 且已过期 → AuthenticationError
        - 其他情况直接返回 token 字符串
        """
        if not self.TOKEN_PATH.exists():
            raise AuthenticationError(
                "未找到认证 Token，请先执行 agenthub login"
            )

        token = self.TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not token:
            raise AuthenticationError(
                "Token 文件为空，请重新执行 agenthub login"
            )

        self._check_jwt_expiry(token)
        return token

    def get_auth_headers(self) -> dict[str, str]:
        """
        读取 token。若为 JWT（三段点分格式）返回 Authorization: Bearer 头，
        否则返回 X-API-Key 头（向后兼容）。
        """
        token = self.load_token()
        if len(token.split(".")) == 3:
            return {"Authorization": f"Bearer {token}"}
        return {"X-API-Key": token}

    def get_jwt_headers(self) -> dict[str, str]:
        """始终返回 Authorization: Bearer 头。"""
        token = self.load_token()
        return {"Authorization": f"Bearer {token}"}

    # ── 内部辅助 ──────────────────────────────────────

    def load_agent_info(self) -> dict[str, str]:
        """从 AGENT_INFO_PATH 读取 agent 信息，返回 {agent_id, name, role}。

        文件不存在时返回空字典。
        """
        if not self.AGENT_INFO_PATH.exists():
            return {}
        try:
            data = _json.loads(self.AGENT_INFO_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}

    def _write_secure(self, path: Path, content: str) -> None:
        """确保父目录权限 0o700，写入文件后 chmod 0o600。"""
        import os
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o600)

    def _check_jwt_expiry(self, token: str) -> None:
        """
        若 token 是 JWT，检查 exp 字段是否已过期。
        非 JWT 格式则跳过检测。
        """
        parts = token.split(".")
        if len(parts) != 3:
            # 不是 JWT，跳过
            return

        payload_b64 = parts[1]
        # JWT base64url 编码，需补齐 padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
        except Exception:
            # 无法解码，视为非 JWT，跳过
            return

        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            raise AuthenticationError(
                "Token 已过期，请重新执行 agenthub login"
            )

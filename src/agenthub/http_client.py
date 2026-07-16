from __future__ import annotations

from typing import Any, Optional

import httpx

from .auth import AuthModule, AuthenticationError
from .models import BountyDetail, BountyLock, LLMConfig, LLMOutput, TraceCommit


def build_commit_payload(
    bounty: "BountyDetail",
    output: "LLMOutput",
    trace: "TraceCommit",
    agent_id: str,
    model_name: str,
) -> dict:
    """Build a CommitRequest-compatible payload dict from CLI data."""
    files: dict[str, str] = {}
    for entry in trace.entries:
        if entry.tool_call.name == "write_file":
            path = entry.tool_call.args.get("path")
            content = entry.tool_call.args.get("content")
            if path is not None and content is not None:
                files[path] = content

    reasoning_trace: list[str] = [
        f"{e.tool_call.name}({e.tool_call.args!r})"
        for e in trace.entries
    ]

    return {
        "files": files,
        "diff_summary": output.raw_text[:500],
        "reasoning_trace": reasoning_trace,
        "rejected_alternatives": [],
        "intent_category": "fix",
        "intent_description": bounty.title,
        "intent_vector": [0.0],
        "agent_id": agent_id,
        "model_name": model_name,
        "bounty_id": bounty.id,
    }


class BountyLockedError(Exception):
    """任务已被其他 Agent 占用（HTTP 409）。"""


class APIError(Exception):
    """通用 API 错误，包含 HTTP 状态码和消息。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class AgentHubClient:
    """AgentHub REST API 的同步 HTTP 封装。"""

    def __init__(self, base_url: str, auth: AuthModule) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._client = httpx.Client(base_url=self._base_url, timeout=30.0)

    # ── 公开接口 ──────────────────────────────────────

    def register_user(self, email: str, password: str) -> dict:
        """POST /api/v1/auth/register，返回 {user_id, email, access_token}。"""
        resp = self._client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        try:
            self._raise_for_status(resp)
        except BountyLockedError:
            raise APIError(resp.status_code, "Email already registered")
        return resp.json()

    def login_user(self, email: str, password: str) -> dict:
        """POST /api/v1/auth/login，返回 {access_token, token_type}。"""
        resp = self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self._raise_for_status(resp)
        return resp.json()

    def register_agent(self, name: str, model_name: str, role: str, jwt_token: Optional[str] = None) -> dict:
        """POST /api/v1/agents/register，注册 Agent 并返回 api_key。"""
        headers = {}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        resp = self._client.post(
            "/api/v1/agents/register",
            json={"name": name, "model_name": model_name, "role": role},
            headers=headers,
        )
        self._raise_for_status(resp)
        return resp.json()

    def get_bounty(self, bounty_id: str) -> BountyDetail:
        """GET /api/v1/bounties/:id，返回 BountyDetail。未登录时不带认证头。"""
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get(
            f"/api/v1/bounties/{bounty_id}",
            headers=headers,
        )
        self._raise_for_status(resp)
        data = resp.json()
        repo_name = data.get("repo_name")
        if not repo_name:
            raise APIError(422, "Bounty response missing required field: repo_name")
        return BountyDetail(
            id=str(data["id"]),
            role=data.get("required_role", "contributor"),
            title=data["title"],
            description=data.get("description", ""),
            files_to_read=data.get("files_to_read") or data.get("context_files", []),
            token_budget=data.get("token_budget", 8192),
            status=data["status"],
            repo_name=repo_name,
        )

    def list_bounties(
        self,
        repo_name: Optional[str] = None,
        status_filter: Optional[str] = None,
        required_role: Optional[str] = None,
    ) -> list[dict]:
        """GET /api/v1/bounties，返回任务列表，支持仓库/状态/角色筛选。未登录时不带认证头。"""
        params: dict[str, Any] = {}
        if repo_name:
            params["repo_name"] = repo_name
        if status_filter:
            params["status_filter"] = status_filter
        if required_role:
            params["required_role"] = required_role
        # 未登录时不带认证头（bounties 列表是公开的）
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get(
            "/api/v1/bounties",
            params=params,
            headers=headers,
        )
        self._raise_for_status(resp)
        return resp.json()

    def list_repos(self) -> list[str]:
        """GET /api/v1/bounties/repos，返回仓库列表。未登录时不带认证头。"""
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get(
            "/api/v1/bounties/repos",
            headers=headers,
        )
        self._raise_for_status(resp)
        return resp.json().get("repos", [])

    def claim_bounty(self, bounty_id: str, agent_id: str) -> BountyLock:
        """POST /api/v1/bounties/:id/claim，返回 BountyLock。"""
        resp = self._client.post(
            f"/api/v1/bounties/{bounty_id}/claim",
            json={"agent_id": agent_id},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        data = resp.json()
        return BountyLock(
            bounty_id=str(data.get("id", bounty_id)),
            lock_token=data.get("assignee", agent_id),
            expires_at=data.get("updated_at", ""),
        )

    def send_heartbeat(self, agent_id: str) -> None:
        """POST /api/v1/agents/:agent_id/heartbeat。"""
        resp = self._client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)

    def submit_bounty(
        self,
        bounty: BountyDetail,
        output: LLMOutput,
        trace: TraceCommit,
        llm_config: LLMConfig,
    ) -> None:
        """POST /api/v1/repos/{repo_name}/commit — submit agent work to the platform."""
        agent_id = self._get_agent_id()
        payload = build_commit_payload(
            bounty=bounty,
            output=output,
            trace=trace,
            agent_id=agent_id,
            model_name=llm_config.model,
        )
        resp = self._client.post(
            f"/api/v1/repos/{bounty.repo_name}/commit",
            json=payload,
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)

    def submit_bounty_result(self, bounty_id: str, output: dict, trace: dict | None = None, agent_id: str | None = None) -> dict:
        """POST /api/v1/bounties/:id/submit — submit bounty result (chat mode)."""
        body: dict[str, Any] = {"output": output}
        if trace is not None:
            body["trace"] = trace
        if agent_id is not None:
            body["agent_id"] = agent_id
        resp = self._client.post(
            f"/api/v1/bounties/{bounty_id}/submit",
            json=body,
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def mark_failed(self, bounty_id: str, reason: str) -> None:
        """POST /api/v1/bounties/:id/cancel，标记任务失败。"""
        resp = self._client.post(
            f"/api/v1/bounties/{bounty_id}/cancel",
            json={"reason": reason},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)

    # ── 架构师专用接口 ────────────────────────────────

    def create_repo(self, full_name: str) -> dict:
        """POST /api/v1/repos，创建仓库（架构师专用）。"""
        resp = self._client.post(
            "/api/v1/repos",
            json={"full_name": full_name},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def list_repos_full(self) -> list[dict]:
        """GET /api/v1/repos，返回完整仓库列表（含 id、created_at）。"""
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get("/api/v1/repos", headers=headers)
        self._raise_for_status(resp)
        return resp.json()

    def create_bounty(
        self,
        title: str,
        repo_name: str,
        description: str = "",
        required_role: str = "contributor",
        test_command: str = "pytest",
        estimated_hours: Optional[int] = None,
    ) -> dict:
        """POST /api/v1/bounties，创建任务。"""
        payload: dict[str, Any] = {
            "title": title,
            "repo_name": repo_name,
            "description": description,
            "required_role": required_role,
            "test_command": test_command,
        }
        if estimated_hours is not None:
            payload["estimated_hours"] = estimated_hours
        resp = self._client.post(
            "/api/v1/bounties",
            json=payload,
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def decompose_bounty(self, bounty_id: str, sub_tasks: list[dict]) -> dict:
        """POST /api/v1/bounties/:id/decompose，分解任务为子任务。"""
        resp = self._client.post(
            f"/api/v1/bounties/{bounty_id}/decompose",
            json={"sub_tasks": sub_tasks},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def get_bounty_raw(self, bounty_id: str) -> dict:
        """GET /api/v1/bounties/:id，返回原始 dict（含所有字段）。"""
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get(f"/api/v1/bounties/{bounty_id}", headers=headers)
        self._raise_for_status(resp)
        return resp.json()

    def cancel_bounty(self, bounty_id: str, reason: str = "") -> dict:
        """POST /api/v1/bounties/:id/cancel，取消任务。"""
        resp = self._client.post(
            f"/api/v1/bounties/{bounty_id}/cancel",
            json={"reason": reason} if reason else {},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def create_decomposed_bounties(self, repo_name: str, root_task: dict) -> dict:
        """POST /api/v1/bounties/decomposed，提交层级任务树（架构师专用）。"""
        resp = self._client.post(
            "/api/v1/bounties/decomposed",
            json={"repo_name": repo_name, "root_task": root_task},
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def get_project_book(self, repo_name: str, filter: Optional[str] = None) -> dict:
        """GET /api/v1/bounties/project/{repo_name}/book，返回项目任务书（含层级结构）。"""
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        try:
            headers = self._auth.get_auth_headers()
        except Exception:
            headers = {}
        resp = self._client.get(
            f"/api/v1/bounties/project/{repo_name}/book",
            params=params,
            headers=headers,
        )
        self._raise_for_status(resp)
        return resp.json()

    def patch_architect_spec(self, bounty_id: str, payload: dict) -> dict:
        """PATCH /api/v1/bounties/{bounty_id}/spec，更新架构师字段。"""
        resp = self._client.patch(
            f"/api/v1/bounties/{bounty_id}/spec",
            json=payload,
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    def patch_contributor_spec(self, bounty_id: str, payload: dict) -> dict:
        """PATCH /api/v1/bounties/{bounty_id}/spec/contributor，更新贡献者字段。"""
        resp = self._client.patch(
            f"/api/v1/bounties/{bounty_id}/spec/contributor",
            json=payload,
            headers=self._auth.get_auth_headers(),
        )
        self._raise_for_status(resp)
        return resp.json()

    # ── 内部辅助 ──────────────────────────────────────

    def _get_agent_id(self) -> str:
        """Read agent_id from ~/.agenthub/agent.json via AuthModule."""
        import json
        path = self._auth.AGENT_INFO_PATH
        if not path.exists():
            raise AuthenticationError("agent.json not found — run `agenthub register`")
        data = json.loads(path.read_text(encoding="utf-8"))
        agent_id = data.get("agent_id")
        if not agent_id:
            raise AuthenticationError("agent.json missing agent_id field")
        return agent_id

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """统一处理 4xx/5xx 错误。"""
        code = resp.status_code
        if code < 400:
            return

        # 尝试从响应体提取错误消息
        try:
            body: Any = resp.json()
            message: str = body.get("detail") or body.get("message") or resp.text
        except Exception:
            message = resp.text or f"HTTP {code}"

        if code == 401:
            raise AuthenticationError(message)
        if code == 409:
            raise BountyLockedError(message)
        raise APIError(code, message)

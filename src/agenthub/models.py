from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# ── 配置 ──────────────────────────────────────────────

@dataclass
class LLMConfig:
    provider: Literal["claude-code", "anthropic"]
    model: str
    api_key: str | None = None


@dataclass
class AppConfig:
    api_base_url: str
    llm: LLMConfig
    workspace_root: str = ""


# ── 技能配置 ──────────────────────────────────────────

@dataclass
class SkillConfig:
    role: str
    system_prompt_template: str
    tool_whitelist: list[str]
    path_rules: list[str]           # glob 规则，如 ["src/**", "tests/**"]
    output_schema: dict[str, Any]   # JSON Schema


# ── Bounty ────────────────────────────────────────────

@dataclass
class BountyDetail:
    id: str
    role: str
    title: str
    description: str
    files_to_read: list[str]
    token_budget: int
    status: str
    repo_name: str


@dataclass
class BountyLock:
    bounty_id: str
    lock_token: str
    expires_at: str                 # ISO 8601


# ── 上下文 ────────────────────────────────────────────

@dataclass
class FileContent:
    path: str
    content: str | None             # None 表示文件缺失
    missing: bool = False


@dataclass
class Context:
    system_prompt: str
    bounty: BountyDetail
    files: list[FileContent]
    token_budget: int


# ── 工具调用 ──────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    output: Any
    allowed: bool                   # False 表示 permission_denied


# ── LLM 输出 ──────────────────────────────────────────

@dataclass
class LLMOutput:
    status: Literal["submitted", "failed"]
    content: dict[str, Any]
    raw_text: str


# ── 验证结果 ──────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    attempt: int = 0


# ── Trace ─────────────────────────────────────────────

@dataclass
class TraceEntry:
    tool_call: ToolCall
    result: ToolResult
    timestamp: str                  # ISO 8601


@dataclass
class TraceCommit:
    bounty_id: str
    role: str
    entries: list[TraceEntry]


# ── 提交 ──────────────────────────────────────────────

@dataclass
class SubmitPayload:
    output: dict[str, Any]
    trace: TraceCommit
    agent_id: str | None = None


# ── 对话模式 ──────────────────────────────────────────

@dataclass
class ChatSession:
    mode: Literal["standalone", "bounty"]
    model: str
    messages: list[dict[str, Any]]          # Anthropic Messages API 格式
    started_at: str                          # ISO 8601
    bounty_id: Optional[str] = None
    bounty: Optional[BountyDetail] = None   # Bounty 模式下的详情


@dataclass
class ChatConfig:
    model: str
    show_tools: bool = True
    save_path: Optional[str] = None
    bounty_id: Optional[str] = None


@dataclass
class ChatHistoryFile:
    session: ChatSession
    ended_at: str                            # ISO 8601
    message_count: int
    model: str

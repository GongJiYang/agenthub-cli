from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from textual.message import Message


@dataclass
class ExecutionStage:
    stage: str


@dataclass
class ExecutionOutput:
    text: str


@dataclass
class ToolCall:
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_name: str
    output: str


@dataclass
class ExecutionComplete:
    success: bool
    message: str = ""


@dataclass
class ExecutionError:
    message: str


EXECUTION_STAGES = ["claim", "context", "execute", "validate", "submit"]


class ExecutionCancelFlag:
    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


def run_execution_pipeline(
    app: Any,
    bounty_id: str,
    api_base_url: str,
    auth: Any,
    cancel_flag: ExecutionCancelFlag,
) -> None:
    """Synchronous execution pipeline that emits Textual messages.

    Call from a @work-decorated async method using run_in_executor or
    thread. Emits messages via app.emit_message at each stage.
    """
    from agenthub.auth import AuthenticationError
    from agenthub.config import load_config
    from agenthub.context_builder import ContextBuilder
    from agenthub.http_client import AgentHubClient
    from agenthub.llm_runner import LLMRunner
    from agenthub.models import SubmitPayload
    from agenthub.schema_validator import SchemaValidator
    from agenthub.skill_loader import SkillLoader
    from agenthub.tool_interceptor import ToolInterceptor
    from agenthub.trace_writer import TraceWriter

    MAX_RETRIES = 3

    def _emit(msg: Message) -> None:
        try:
            app.call_from_thread(app.emit_message, msg)
        except Exception:
            pass

    # Stage 1: Claim
    if cancel_flag.is_set():
        _emit(ExecutionError(message="用户取消"))
        return

    _emit(ExecutionStage(stage="claim"))

    try:
        auth.load_token()
    except AuthenticationError as e:
        _emit(ExecutionError(message=f"认证失败: {e}"))
        return

    app_config = load_config()
    client = AgentHubClient(base_url=api_base_url, auth=auth)

    # Stage 2: Context
    if cancel_flag.is_set():
        _emit(ExecutionError(message="用户取消"))
        return

    _emit(ExecutionStage(stage="context"))
    _emit(ExecutionOutput(text=f"加载任务 {bounty_id}..."))

    try:
        bounty = client.get_bounty(bounty_id)
    except Exception as e:
        _emit(ExecutionError(message=f"加载任务失败: {e}"))
        return

    skill_loader = SkillLoader()
    skill_config = skill_loader.load(bounty.role)

    context_builder = ContextBuilder(client=client)
    context = context_builder.build(bounty_id, skill_config)

    # Stage 3: Execute
    if cancel_flag.is_set():
        _emit(ExecutionError(message="用户取消"))
        return

    _emit(ExecutionStage(stage="execute"))
    _emit(ExecutionOutput(text="开始执行..."))

    trace_writer = TraceWriter()
    interceptor = ToolInterceptor(skill_config=skill_config, trace_writer=trace_writer)
    llm_runner = LLMRunner(config=app_config.llm, interceptor=interceptor)

    output = None
    validation_result = None

    for attempt in range(MAX_RETRIES):
        if cancel_flag.is_set():
            client.mark_failed(bounty_id, "用户取消")
            _emit(ExecutionError(message="用户取消"))
            return

        _emit(ExecutionOutput(text=f"LLM 推理 (尝试 {attempt + 1}/{MAX_RETRIES})..."))

        try:
            output = llm_runner.run(context)
        except Exception as e:
            _emit(ExecutionOutput(text=f"LLM 执行错误: {e}"))

        if output is None:
            if attempt < MAX_RETRIES - 1:
                continue
            client.mark_failed(bounty_id, f"LLM 执行失败")
            _emit(ExecutionError(message="LLM 执行失败"))
            return

        # Stage 4: Validate
        _emit(ExecutionStage(stage="validate"))

        validator = SchemaValidator()
        validation_result = validator.validate(
            output.content, skill_config, attempt
        )

        if validation_result.ok:
            break

        if attempt < MAX_RETRIES - 1:
            _emit(ExecutionOutput(
                text=f"验证失败，重试中... 错误: {'; '.join(validation_result.errors)}"
            ))

    if not validation_result or not validation_result.ok:
        reason = "; ".join(validation_result.errors) if validation_result else "未知验证错误"
        client.mark_failed(bounty_id, reason)
        _emit(ExecutionError(message=f"验证失败: {reason}"))
        return

    # Stage 5: Submit
    if cancel_flag.is_set():
        client.mark_failed(bounty_id, "用户取消")
        _emit(ExecutionError(message="用户取消"))
        return

    _emit(ExecutionStage(stage="submit"))
    _emit(ExecutionOutput(text="提交结果..."))

    trace_commit = trace_writer.to_trace_commit(
        bounty_id=bounty_id,
        role=bounty.role,
    )
    payload = SubmitPayload(output=output.content, trace=trace_commit)

    try:
        client.submit_bounty(bounty_id, payload)
    except Exception as e:
        _emit(ExecutionError(message=f"提交失败: {e}"))
        return

    _emit(ExecutionComplete(success=True, message="任务执行完成并已提交"))
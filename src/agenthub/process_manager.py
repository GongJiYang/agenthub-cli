"""ProcessManager：编排完整的 Bounty 执行流程。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .auth import AuthModule, AuthenticationError
from .config import load_config
from .context_builder import ContextBuilder
from .http_client import AgentHubClient
from .llm_runner import LLMRunner
from .models import LLMConfig
from .schema_validator import SchemaValidator
from .skill_loader import SkillLoader
from .tool_interceptor import ToolInterceptor
from .trace_writer import TraceWriter

MAX_RETRIES = 3

EXECUTION_STAGES = {
    "auth":        "🔐 验证身份",
    "load_skill":  "📋 加载技能配置",
    "load_bounty": "📦 拉取任务详情",
    "build_context": "🏗️ 构建上下文",
    "run_llm":     "🤖 执行 LLM 推理",
    "validate":    "✅ 验证输出",
    "submit":      "📤 提交结果",
}


class ProcessManager:
    def __init__(
        self,
        client: AgentHubClient,
        auth: AuthModule,
        skill_loader: SkillLoader,
        context_builder: ContextBuilder,
        schema_validator: SchemaValidator,
        bounty_id: str,
        heartbeat_interval: int = 30,
        workspace_root: str = "",
    ) -> None:
        self._client = client
        self._auth = auth
        self._skill_loader = skill_loader
        self._context_builder = context_builder
        self._schema_validator = schema_validator
        self._bounty_id = bounty_id
        self._heartbeat_interval = heartbeat_interval
        self._workspace_root = workspace_root

        self._heartbeat_stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    # ── 公开接口 ──────────────────────────────────────

    def run(self) -> int:
        """编排完整执行流程，返回退出码（0=成功，1=失败）。"""
        try:
            self._start_heartbeat()
            return self._execute()
        except AuthenticationError as e:
            print(f"认证失败：{e}\n请执行 agenthub login")
            return 1
        except Exception:
            self._release_lock("failed", "未捕获异常")
            raise
        finally:
            self._stop_heartbeat()

    # ── 内部执行流程 ──────────────────────────────────

    def _execute(self) -> int:
        # 1. 验证身份
        self._print_stage("auth")
        try:
            self._auth.load_token()
        except AuthenticationError:
            raise

        # 2. 加载技能配置
        self._print_stage("load_skill")
        bounty = self._client.get_bounty(self._bounty_id)
        skill_config = self._skill_loader.load(bounty.role)

        # 3. 拉取任务详情 + 构造上下文
        self._print_stage("build_context")
        context = self._context_builder.build(self._bounty_id, skill_config)

        # 4. 创建 TraceWriter、ToolInterceptor、LLMRunner
        self._print_stage("run_llm", "准备 LLM 推理环境")
        app_config = load_config()
        trace_writer = TraceWriter()
        interceptor = ToolInterceptor(skill_config=skill_config, trace_writer=trace_writer)
        llm_runner = LLMRunner(config=app_config.llm, interceptor=interceptor)

        # 5-9. 执行 LLM 推理 + 验证（最多 MAX_RETRIES 次）
        output = None
        validation_result = None

        for attempt in range(MAX_RETRIES):
            self._print_stage("run_llm", f"LLM 推理（第 {attempt + 1}/{MAX_RETRIES} 次）")
            output = llm_runner.run(context)
            validation_result = self._schema_validator.validate(
                output.content, skill_config, attempt
            )

            if validation_result.ok:
                break

            if attempt < MAX_RETRIES - 1:
                print(f"⚠️ 验证失败（第 {attempt + 1} 次）：{'; '.join(validation_result.errors)}")
                print("  重试中...")

        # 验证失败 3 次
        if not validation_result.ok:
            reason = "; ".join(validation_result.errors)
            print(f"❌ 验证失败（已重试 {MAX_RETRIES} 次）：{reason}")
            self._client.mark_failed(self._bounty_id, reason)
            return 1

        # 验证通过，提交
        self._print_stage("submit")
        trace_commit = trace_writer.to_trace_commit(
            bounty_id=self._bounty_id,
            role=bounty.role,
        )
        self._client.submit_bounty(
            bounty=bounty,
            output=output,
            trace=trace_commit,
            llm_config=app_config.llm,
        )
        print("✅ 提交成功！")
        return 0

    # ── 心跳 ──────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        """启动后台心跳线程，每 heartbeat_interval 秒调用一次 send_heartbeat。"""
        self._heartbeat_stop_event.clear()

        def _heartbeat_loop() -> None:
            while not self._heartbeat_stop_event.wait(timeout=self._heartbeat_interval):
                try:
                    self._client.send_heartbeat(self._bounty_id)
                except Exception:
                    # 心跳失败只记录警告，不中断主流程
                    pass

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            daemon=True,
            name=f"heartbeat-{self._bounty_id}",
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        """停止心跳线程。"""
        self._heartbeat_stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    # ── 锁释放 ────────────────────────────────────────

    def _release_lock(self, status: str, reason: str = "") -> None:
        """释放 Bounty_Lock，标记任务状态。"""
        try:
            if status == "failed":
                self._client.mark_failed(self._bounty_id, reason)
        except Exception:
            pass

    @staticmethod
    def _print_stage(stage: str, detail: str = "") -> None:
        """打印执行阶段进度到终端。"""
        label = EXECUTION_STAGES.get(stage, stage)
        msg = f"{label}"
        if detail:
            msg += f" — {detail}"
        print(msg)

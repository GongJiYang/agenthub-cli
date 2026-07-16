"""ProcessManager 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from agenthub.auth import AuthenticationError
from agenthub.models import (
    BountyDetail,
    Context,
    FileContent,
    LLMOutput,
    SkillConfig,
    SubmitPayload,
    TraceCommit,
    ValidationResult,
)
from agenthub.process_manager import ProcessManager, MAX_RETRIES


# ── 测试夹具 ──────────────────────────────────────────────────────────────────

def _make_bounty() -> BountyDetail:
    return BountyDetail(
        id="bounty-123",
        role="contributor",
        title="Test Bounty",
        description="Implement feature X",
        files_to_read=["src/main.py"],
        token_budget=4096,
        status="claimed",
        repo_name="test-repo",
    )


def _make_skill_config() -> SkillConfig:
    return SkillConfig(
        role="contributor",
        system_prompt_template="You are a contributor. {{ bounty.description }}",
        tool_whitelist=["read_file", "write_file"],
        path_rules=["src/**", "tests/**"],
        output_schema={
            "type": "object",
            "required": ["status", "summary"],
            "properties": {
                "status": {"type": "string"},
                "summary": {"type": "string"},
            },
        },
    )


def _make_context(bounty: BountyDetail) -> Context:
    return Context(
        system_prompt="You are a contributor.",
        bounty=bounty,
        files=[FileContent(path="src/main.py", content="print('hello')", missing=False)],
        token_budget=4096,
    )


def _make_llm_output(ok: bool = True) -> LLMOutput:
    content = {"status": "submitted", "summary": "Done"} if ok else {"bad": "output"}
    return LLMOutput(status="submitted", content=content, raw_text="")


def _make_trace_commit(bounty_id: str = "bounty-123") -> TraceCommit:
    return TraceCommit(bounty_id=bounty_id, role="contributor", entries=[])


def _make_process_manager(
    client=None,
    auth=None,
    skill_loader=None,
    context_builder=None,
    schema_validator=None,
    bounty_id="bounty-123",
    heartbeat_interval=30,
) -> ProcessManager:
    return ProcessManager(
        client=client or MagicMock(),
        auth=auth or MagicMock(),
        skill_loader=skill_loader or MagicMock(),
        context_builder=context_builder or MagicMock(),
        schema_validator=schema_validator or MagicMock(),
        bounty_id=bounty_id,
        heartbeat_interval=heartbeat_interval,
    )


# ── 测试用例 ──────────────────────────────────────────────────────────────────

class TestProcessManagerSuccess:
    """完整成功流程：验证通过，submit 被调用，返回 0。"""

    def test_full_success_returns_zero(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=True)
        trace_commit = _make_trace_commit()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        auth.load_token.return_value = "valid-token"

        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config

        context_builder = MagicMock()
        context_builder.build.return_value = context

        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(ok=True, attempt=0)

        app_config = MagicMock()
        app_config.llm = MagicMock()

        trace_writer_mock = MagicMock()
        trace_writer_mock.to_trace_commit.return_value = trace_commit

        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            heartbeat_interval=9999,  # 避免心跳在测试中触发
        )

        with patch("agenthub.process_manager.load_config", return_value=app_config), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            result = pm.run()

        assert result == 0
        client.submit_bounty.assert_called_once()
        client.mark_failed.assert_not_called()

    def test_submit_called_with_correct_bounty_id(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=True)
        trace_commit = _make_trace_commit()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context
        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(ok=True, attempt=0)

        trace_writer_mock = MagicMock()
        trace_writer_mock.to_trace_commit.return_value = trace_commit
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            bounty_id="bounty-123",
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            pm.run()

        submit_call_args = client.submit_bounty.call_args
        passed_bounty = submit_call_args.kwargs.get("bounty") or submit_call_args[0][0]
        assert isinstance(passed_bounty, BountyDetail)
        assert passed_bounty.id == "bounty-123"
        assert passed_bounty.repo_name == "test-repo"

    def test_process_manager_does_not_pass_submit_payload(self):
        """submit_bounty should not receive a SubmitPayload instance."""
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=True)
        trace_commit = _make_trace_commit()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context
        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(ok=True, attempt=0)

        trace_writer_mock = MagicMock()
        trace_writer_mock.to_trace_commit.return_value = trace_commit
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            pm.run()

        submit_call_args = client.submit_bounty.call_args
        all_args = list(submit_call_args.args) + list(submit_call_args.kwargs.values())
        assert not any(isinstance(arg, SubmitPayload) for arg in all_args)


class TestProcessManagerRetry:
    """验证失败重试：第 1 次失败，第 2 次成功，submit 被调用。"""

    def test_retry_on_first_failure_then_success(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=True)
        trace_commit = _make_trace_commit()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context

        # 第 1 次验证失败，第 2 次成功
        schema_validator = MagicMock()
        schema_validator.validate.side_effect = [
            ValidationResult(ok=False, errors=["missing field"], attempt=0),
            ValidationResult(ok=True, attempt=1),
        ]

        trace_writer_mock = MagicMock()
        trace_writer_mock.to_trace_commit.return_value = trace_commit
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            result = pm.run()

        assert result == 0
        # LLM 被调用了 2 次
        assert llm_runner_mock.run.call_count == 2
        # submit 被调用
        client.submit_bounty.assert_called_once()
        client.mark_failed.assert_not_called()


class TestProcessManagerMaxRetries:
    """验证连续失败 3 次：mark_failed 被调用，返回 1。"""

    def test_three_consecutive_failures_calls_mark_failed(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=False)

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context

        # 3 次都失败
        schema_validator = MagicMock()
        schema_validator.validate.side_effect = [
            ValidationResult(ok=False, errors=["error 1"], attempt=0),
            ValidationResult(ok=False, errors=["error 2"], attempt=1),
            ValidationResult(ok=False, errors=["error 3"], attempt=2),
        ]

        trace_writer_mock = MagicMock()
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            result = pm.run()

        assert result == 1
        client.mark_failed.assert_called_once()
        client.submit_bounty.assert_not_called()
        # LLM 被调用了 3 次
        assert llm_runner_mock.run.call_count == MAX_RETRIES

    def test_mark_failed_called_with_bounty_id(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=False)

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context

        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(
            ok=False, errors=["bad output"], attempt=0
        )

        trace_writer_mock = MagicMock()
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            bounty_id="bounty-456",
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            pm.run()

        mark_failed_call = client.mark_failed.call_args
        assert mark_failed_call[0][0] == "bounty-456"

    def test_process_manager_mark_failed_unchanged(self):
        """mark_failed is still called with (bounty_id, reason) on validation failure."""
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=False)

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context

        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(
            ok=False, errors=["field missing", "invalid type"], attempt=0
        )

        trace_writer_mock = MagicMock()
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            bounty_id="bounty-999",
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            result = pm.run()

        assert result == 1
        client.mark_failed.assert_called_once()
        mark_failed_args = client.mark_failed.call_args[0]
        assert mark_failed_args[0] == "bounty-999"
        assert isinstance(mark_failed_args[1], str)
        assert len(mark_failed_args[1]) > 0


class TestProcessManagerAuthError:
    """AuthenticationError：返回 1，不调用 submit。"""

    def test_auth_error_returns_one(self):
        auth = MagicMock()
        auth.load_token.side_effect = AuthenticationError("Token 不存在")

        pm = _make_process_manager(auth=auth, heartbeat_interval=9999)

        result = pm.run()

        assert result == 1

    def test_auth_error_does_not_call_submit(self):
        client = MagicMock()
        auth = MagicMock()
        auth.load_token.side_effect = AuthenticationError("Token 已过期")

        pm = _make_process_manager(
            client=client, auth=auth, heartbeat_interval=9999
        )

        pm.run()

        client.submit_bounty.assert_not_called()

    def test_auth_error_does_not_call_mark_failed(self):
        """AuthenticationError 不应触发 mark_failed（任务未开始执行）。"""
        client = MagicMock()
        auth = MagicMock()
        auth.load_token.side_effect = AuthenticationError("Token 不存在")

        pm = _make_process_manager(
            client=client, auth=auth, heartbeat_interval=9999
        )

        pm.run()

        client.mark_failed.assert_not_called()


class TestProcessManagerUnhandledException:
    """未捕获异常：mark_failed 被调用，异常被 re-raise。"""

    def test_unexpected_exception_calls_mark_failed(self):
        bounty = _make_bounty()
        skill_config = _make_skill_config()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config

        context_builder = MagicMock()
        context_builder.build.side_effect = RuntimeError("Unexpected network error")

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            heartbeat_interval=9999,
        )

        with pytest.raises(RuntimeError, match="Unexpected network error"):
            pm.run()

        client.mark_failed.assert_called_once()

    def test_unexpected_exception_is_reraised(self):
        bounty = _make_bounty()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.side_effect = ValueError("Skill config corrupted")

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            heartbeat_interval=9999,
        )

        with pytest.raises(ValueError, match="Skill config corrupted"):
            pm.run()

    def test_mark_failed_called_with_bounty_id_on_exception(self):
        bounty = _make_bounty()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.side_effect = RuntimeError("boom")

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            bounty_id="bounty-789",
            heartbeat_interval=9999,
        )

        with pytest.raises(RuntimeError):
            pm.run()

        mark_failed_call = client.mark_failed.call_args
        assert mark_failed_call[0][0] == "bounty-789"


class TestProcessManagerHeartbeat:
    """心跳线程行为测试。"""

    def test_heartbeat_stops_after_run(self):
        """run() 完成后心跳线程应停止。"""
        bounty = _make_bounty()
        skill_config = _make_skill_config()
        context = _make_context(bounty)
        llm_output = _make_llm_output(ok=True)
        trace_commit = _make_trace_commit()

        client = MagicMock()
        client.get_bounty.return_value = bounty

        auth = MagicMock()
        skill_loader = MagicMock()
        skill_loader.load.return_value = skill_config
        context_builder = MagicMock()
        context_builder.build.return_value = context
        schema_validator = MagicMock()
        schema_validator.validate.return_value = ValidationResult(ok=True, attempt=0)

        trace_writer_mock = MagicMock()
        trace_writer_mock.to_trace_commit.return_value = trace_commit
        llm_runner_mock = MagicMock()
        llm_runner_mock.run.return_value = llm_output

        pm = _make_process_manager(
            client=client,
            auth=auth,
            skill_loader=skill_loader,
            context_builder=context_builder,
            schema_validator=schema_validator,
            heartbeat_interval=9999,
        )

        with patch("agenthub.process_manager.load_config"), \
             patch("agenthub.process_manager.TraceWriter", return_value=trace_writer_mock), \
             patch("agenthub.process_manager.ToolInterceptor"), \
             patch("agenthub.process_manager.LLMRunner", return_value=llm_runner_mock):
            pm.run()

        # 心跳线程应已停止
        assert pm._heartbeat_thread is None
        assert pm._heartbeat_stop_event.is_set()

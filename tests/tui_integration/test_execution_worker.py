from agenthub.auth import AuthenticationError
from agenthub.tui.workers.execution_worker import (
    ExecutionCancelFlag,
    ExecutionComplete,
    ExecutionError,
    ExecutionOutput,
    ExecutionStage,
    EXECUTION_STAGES,
    ToolCall,
    ToolResult,
    run_execution_pipeline,
)


def test_execution_stages_defined():
    assert EXECUTION_STAGES == ["claim", "context", "execute", "validate", "submit"]


def test_execution_cancel_flag_initial_state():
    flag = ExecutionCancelFlag()
    assert not flag.is_set()


def test_execution_cancel_flag_set_clear():
    flag = ExecutionCancelFlag()
    flag.set()
    assert flag.is_set()
    flag.clear()
    assert not flag.is_set()


def test_execution_stage_message():
    msg = ExecutionStage(stage="execute")
    assert msg.stage == "execute"


def test_execution_output_message():
    msg = ExecutionOutput(text="loading...")
    assert msg.text == "loading..."


def test_execution_complete_success():
    msg = ExecutionComplete(success=True, message="done")
    assert msg.success is True
    assert msg.message == "done"


def test_execution_complete_failure():
    msg = ExecutionComplete(success=False, message="failed")
    assert msg.success is False


def test_execution_error_message():
    msg = ExecutionError(message="auth failed")
    assert msg.message == "auth failed"


def test_tool_call_message():
    msg = ToolCall(tool_name="read_file", args={"path": "/tmp/test.py"})
    assert msg.tool_name == "read_file"
    assert msg.args["path"] == "/tmp/test.py"


def test_tool_result_message():
    msg = ToolResult(tool_name="read_file", output="file contents here")
    assert msg.tool_name == "read_file"
    assert msg.output == "file contents here"


def test_run_execution_pipeline_requires_auth():
    flag = ExecutionCancelFlag()

    class FakeApp:
        messages = []
        def call_from_thread(self, handler, msg):
            self.messages.append(msg)
        def emit_message(self, msg):
            self.messages.append(msg)

    class FakeAuth:
        def load_token(self):
            raise AuthenticationError("no token")

    app = FakeApp()
    auth = FakeAuth()
    run_execution_pipeline(app, "bounty-1", "http://localhost:8000/api/v1", auth, flag)

    error_msgs = [m for m in app.messages if isinstance(m, ExecutionError)]
    assert len(error_msgs) >= 1
    assert "认证失败" in error_msgs[0].message


def test_run_execution_pipeline_cancel_before_start():
    flag = ExecutionCancelFlag()
    flag.set()

    class FakeApp:
        messages = []
        def call_from_thread(self, handler, msg):
            self.messages.append(msg)
        def emit_message(self, msg):
            self.messages.append(msg)

    class FakeAuth:
        def load_token(self):
            return None

    app = FakeApp()
    auth = FakeAuth()
    run_execution_pipeline(app, "bounty-1", "http://localhost:8000/api/v1", auth, flag)

    error_msgs = [m for m in app.messages if isinstance(m, ExecutionError)]
    assert len(error_msgs) >= 1
    assert "取消" in error_msgs[0].message
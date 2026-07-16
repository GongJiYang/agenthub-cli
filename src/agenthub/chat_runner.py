"""Chat_Runner：管理对话循环、流式输出和工具执行的核心组件。"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .auth import AuthModule, AuthenticationError
from .http_client import AgentHubClient, APIError
from .models import AppConfig, BountyDetail, ChatSession, ToolCall, ToolResult
from .stream_printer import StreamPrinter
from .tool_executor import ToolExecutor

# 注入 LLM 的工具定义
CHAT_TOOLS = [
    {
        "name": "read_file",
        "description": "读取指定路径的文件内容",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "将内容写入指定路径的文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "在当前工作目录执行 shell 命令",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出指定目录的文件和子目录",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "在代码库中搜索匹配模式的文件和行",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索的正则表达式或文本模式"},
                "path": {"type": "string", "default": ".", "description": "搜索的根目录"},
                "file_pattern": {"type": "string", "default": "*", "description": "文件名 glob 过滤器，如 *.py"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_tests",
        "description": "执行测试命令并返回结果",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "default": "pytest", "description": "测试命令，如 pytest tests/test_foo.py -v"},
                "working_dir": {"type": "string", "default": "", "description": "执行目录，默认为当前目录"},
            },
            "required": [],
        },
    },
    {
        "name": "add_comment",
        "description": "在代码文件中添加注释行",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "目标文件路径"},
                "line": {"type": "integer", "default": 0, "description": "插入注释的行号（1-based），0表示末尾"},
                "message": {"type": "string", "description": "注释内容"},
            },
            "required": ["file", "message"],
        },
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class ChatRunner:
    """核心对话循环管理器。"""

    MAX_RETRIES = 3
    RETRY_WAIT = 10  # 秒

    def __init__(
        self,
        config: AppConfig,
        auth: AuthModule,
        bounty_id: Optional[str],
        model: str,
        show_tools: bool,
        save_path: Optional[str],
        client: Optional[AgentHubClient] = None,
        printer: Optional[StreamPrinter] = None,
        executor: Optional[ToolExecutor] = None,
    ) -> None:
        self._config = config
        self._auth = auth
        self._bounty_id = bounty_id
        self._model = model
        self._show_tools = show_tools
        self._save_path = save_path

        # 依赖注入（便于测试）
        self._client = client
        self._printer = printer or StreamPrinter(show_tools=show_tools)
        self._executor = executor or ToolExecutor()

        self._session: Optional[ChatSession] = None
        self._last_ctrl_c: float = 0.0
        self._exit_requested = False

    # ── 公开接口 ──────────────────────────────────────

    def run(self) -> int:
        """启动对话循环，返回退出码。"""
        try:
            self._session = self._init_session()
            self._printer.print_welcome(
                mode=self._session.mode,
                bounty_id=self._session.bounty_id,
            )
            self._loop()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
        except Exception as e:
            self._handle_crash(e)
            return 1

    # ── 初始化 ────────────────────────────────────────

    def _init_session(self) -> ChatSession:
        """初始化会话，Bounty 模式下拉取 Bounty 详情。"""
        if self._bounty_id:
            return self._init_bounty_session()
        return ChatSession(
            mode="standalone",
            model=self._model,
            messages=[],
            started_at=_now_iso(),
        )

    def _init_bounty_session(self) -> ChatSession:
        """Bounty 模式：拉取 Bounty 详情，失败时以退出码 1 终止。"""
        if self._client is None:
            self._client = AgentHubClient(
                base_url=self._config.api_base_url, auth=self._auth
            )
        try:
            bounty = self._client.get_bounty(self._bounty_id)  # type: ignore[arg-type]
        except (APIError, AuthenticationError) as e:
            print(f"错误：无法加载 Bounty {self._bounty_id}：{e}")
            raise SystemExit(1)

        # 打印 Bounty 摘要
        summary = bounty.description[:200] + ("..." if len(bounty.description) > 200 else "")
        print(f"📋 Bounty：{bounty.title}")
        print(f"   {summary}\n")

        return ChatSession(
            mode="bounty",
            model=self._model,
            messages=[],
            started_at=_now_iso(),
            bounty_id=self._bounty_id,
            bounty=bounty,
        )

    def _build_system_prompt(self, bounty: Optional[BountyDetail] = None) -> str:
        """构建 system prompt，Bounty 模式下注入 Bounty 标题和描述。"""
        if bounty:
            return (
                f"你是一名 AI 助手，正在协助完成以下 Bounty 任务。\n\n"
                f"任务标题：{bounty.title}\n\n"
                f"任务描述：{bounty.description}\n\n"
                f"请根据用户的指引完成任务，可以使用提供的工具进行文件操作和命令执行。"
            )
        return (
            "你是一名 AI 助手，可以帮助用户完成代码编写、文件操作、命令执行等任务。"
            "\n请根据用户的需求提供帮助，可以使用提供的工具进行实际操作。"
        )

    # ── 对话循环 ──────────────────────────────────────

    def _loop(self) -> None:
        """主对话循环。"""
        assert self._session is not None

        while not self._exit_requested:
            try:
                prompt = (
                    f"[bounty:{self._session.bounty_id}] > "
                    if self._session.mode == "bounty"
                    else "> "
                )
                user_input = input(prompt).strip()
            except KeyboardInterrupt:
                now = time.time()
                if now - self._last_ctrl_c < 1.0:
                    # 双击 Ctrl+C，直接退出
                    print()
                    raise SystemExit(0)
                self._last_ctrl_c = now
                # 单次 Ctrl+C 在提示符处，触发 /exit
                print()
                self._handle_command("/exit")
                continue
            except EOFError:
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                should_continue = self._handle_command(user_input)
                if not should_continue:
                    break
            else:
                self._send_message(user_input)

    # ── 命令处理 ──────────────────────────────────────

    def _handle_command(self, cmd: str) -> bool:
        """处理特殊命令，返回 True 表示继续循环，False 表示退出。"""
        cmd = cmd.strip().lower()

        if cmd == "/exit":
            answer = input("是否保存对话历史？[y/N] ").strip().lower()
            if answer in ("y", "yes"):
                self._save_history()
            self._exit_requested = True
            return False

        elif cmd == "/save":
            self._save_history()
            return True

        elif cmd == "/clear":
            assert self._session is not None
            self._session.messages.clear()
            print("[已清空对话历史]")
            return True

        elif cmd == "/submit":
            if self._session and self._session.mode == "bounty":
                return self._handle_submit()
            else:
                print("[提示] /submit 仅在 Bounty 模式下可用")
                return True

        else:
            print(f"[未知命令] {cmd}，可用命令：/exit  /save  /clear" +
                  ("  /submit" if self._session and self._session.mode == "bounty" else ""))
            return True

    def _handle_submit(self) -> bool:
        """处理 /submit 命令（Bounty 模式）。"""
        assert self._session is not None
        answer = input("确认提交 Bounty 结果？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("[已取消]")
            return True

        if self._client is None or self._session.bounty_id is None:
            print("错误：无法提交，客户端未初始化")
            return True

        # 构造简单摘要作为提交内容
        agent_info = self._auth.load_agent_info()
        try:
            self._client.submit_bounty_result(
                bounty_id=self._session.bounty_id,
                output={"summary": f"对话会话，共 {len(self._session.messages)} 条消息"},
                agent_id=agent_info.get("agent_id"),
            )
            print("✅ 提交成功！")
            self._exit_requested = True
            return False
        except Exception as e:
            print(f"❌ 提交失败：{e}")
            return True

    # ── 消息发送 ──────────────────────────────────────

    def _send_message(self, user_input: str) -> None:
        """追加用户消息到历史并调用 LLM，处理流式响应和工具调用。"""
        assert self._session is not None

        # 追加用户消息
        self._session.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_input}],
        })

        system_prompt = self._build_system_prompt(
            self._session.bounty if self._session.mode == "bounty" else None
        )

        for attempt in range(self.MAX_RETRIES):
            try:
                self._call_llm_streaming(system_prompt)
                return
            except KeyboardInterrupt:
                # Ctrl+C 中断生成
                self._printer.print_interrupted()
                # 标记最后一条 assistant 消息为中断
                if (self._session.messages and
                        self._session.messages[-1]["role"] == "assistant"):
                    content = self._session.messages[-1].get("content", [])
                    if content and isinstance(content, list):
                        content[-1]["interrupted"] = True
                return
            except Exception as e:
                err_str = str(e)
                # 429 速率限制重试
                if "429" in err_str or "rate_limit" in err_str.lower():
                    if attempt < self.MAX_RETRIES - 1:
                        print(f"\n[速率限制] 等待 {self.RETRY_WAIT} 秒后重试（{attempt + 1}/{self.MAX_RETRIES}）...")
                        time.sleep(self.RETRY_WAIT)
                        continue
                # 5xx 或网络错误，返回提示符
                print(f"\n[错误] {e}")
                return

    def _call_llm_streaming(self, system_prompt: str) -> None:
        """调用 Anthropic API 流式接口，处理 token 和工具调用。"""
        assert self._session is not None

        try:
            import anthropic as anthropic_sdk
        except ImportError:
            print("错误：anthropic SDK 未安装，请执行：pip install anthropic")
            return

        api_key = self._config.llm.api_key
        if not api_key:
            print(
                "错误：未配置 Anthropic API Key。\n"
                "请在 ~/.agenthub/config.yaml 中添加：\n"
                "  llm:\n"
                "    provider: anthropic\n"
                "    api_key: sk-ant-..."
            )
            return
        client = anthropic_sdk.Anthropic(api_key=api_key)

        messages = self._session.messages.copy()

        while True:
            partial_text = ""
            tool_calls_in_response: list[dict[str, Any]] = []

            with client.messages.stream(
                model=self._model,
                max_tokens=8192,
                system=system_prompt,
                messages=messages,
                tools=CHAT_TOOLS,  # type: ignore[arg-type]
            ) as stream:
                for event in stream:
                    event_type = type(event).__name__

                    if event_type == "RawContentBlockDeltaEvent":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            text = getattr(delta, "text", "")
                            partial_text += text
                            self._printer.print_token(text)

                    elif event_type == "RawContentBlockStartEvent":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            tool_calls_in_response.append({
                                "id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                                "input": {},
                            })

                    elif event_type == "RawContentBlockStopEvent":
                        pass  # tool input 在 InputJsonDelta 中累积

                    elif hasattr(event, "delta") and getattr(getattr(event, "delta", None), "type", None) == "input_json_delta":
                        if tool_calls_in_response:
                            partial_json = getattr(event.delta, "partial_json", "")
                            existing = tool_calls_in_response[-1].get("input_raw", "")
                            tool_calls_in_response[-1]["input_raw"] = existing + partial_json

            self._printer.print_newline()

            # 解析工具调用的 input
            for tc_data in tool_calls_in_response:
                raw = tc_data.pop("input_raw", "{}")
                try:
                    tc_data["input"] = json.loads(raw)
                except json.JSONDecodeError:
                    tc_data["input"] = {}

            # 构建 assistant 消息内容
            assistant_content: list[dict[str, Any]] = []
            if partial_text:
                assistant_content.append({"type": "text", "text": partial_text})
            for tc_data in tool_calls_in_response:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "input": tc_data["input"],
                })

            messages.append({"role": "assistant", "content": assistant_content})
            self._session.messages.append({"role": "assistant", "content": assistant_content})

            if not tool_calls_in_response:
                break

            # 执行工具调用
            tool_result_content: list[dict[str, Any]] = []
            for tc_data in tool_calls_in_response:
                tool_call = ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    args=tc_data["input"],
                )
                self._printer.print_tool_call(tool_call)
                result: ToolResult = self._executor.execute(tool_call)
                result_str = str(result.output)
                self._printer.print_tool_result(tool_call, result_str)

                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result_str,
                })

            tool_result_msg = {"role": "user", "content": tool_result_content}
            messages.append(tool_result_msg)
            self._session.messages.append(tool_result_msg)

    # ── 历史保存 ──────────────────────────────────────

    def _save_history(self, path: Optional[str] = None) -> None:
        """将 ChatSession 序列化为 JSON 保存。"""
        assert self._session is not None

        save_path = path or self._save_path
        if not save_path:
            ts = _timestamp()
            save_path = str(
                Path(f"~/.agenthub/chat_history_{ts}.json").expanduser()
            )

        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "started_at": self._session.started_at,
            "ended_at": _now_iso(),
            "model": self._session.model,
            "message_count": len(self._session.messages),
            "mode": self._session.mode,
            "bounty_id": self._session.bounty_id,
            "messages": self._session.messages,
        }

        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[已保存] {save_path}")

    def _handle_crash(self, exc: Exception) -> None:
        """未捕获异常时自动保存历史到 crash 文件。"""
        ts = _timestamp()
        crash_path = str(
            Path(f"~/.agenthub/chat_crash_{ts}.json").expanduser()
        )
        try:
            self._save_history(crash_path)
        except Exception:
            pass
        print(f"[崩溃] 未捕获异常：{exc}")
        print(f"[崩溃] 对话历史已保存至：{crash_path}")

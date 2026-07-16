from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from ...auth import AuthModule
from ...config import load_config
from ...http_client import AgentHubClient

ROLES = ["contributor", "architect", "executor", "reviewer", "tester"]


class LoginScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "返回", show=True),
        Binding("tab", "toggle_mode", "切换模式", show=True),
        Binding("r", "cycle_role", "切换角色", show=True),
        Binding("enter", "try_login", "登录/注册", show=False),
    ]

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
    }

    LoginScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    LoginScreen .mode-label {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    LoginScreen Input {
        margin-bottom: 1;
    }

    LoginScreen .error-label {
        color: red;
        text-align: center;
        margin-bottom: 1;
    }

    LoginScreen .submit-btn {
        align: center middle;
    }

    LoginScreen .role-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._is_register = False
        self._role_idx = 0
        self._api_base_url: str = ""
        self._auth: object | None = None

    def set_api_context(self, api_base_url: str, auth: object) -> None:
        self._api_base_url = api_base_url
        self._auth = auth

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("🔐 登录", id="mode-label", classes="mode-label")
            yield Input(placeholder="邮箱", id="email-input")
            yield Input(placeholder="密码", password=True, id="password-input")
            yield Input(placeholder="确认密码", password=True, id="confirm-input")
            yield Static("", id="role-label", classes="role-hint")
            yield Static("", id="error-label", classes="error-label")
            yield Button("登录", variant="success", id="submit-btn", classes="submit-btn")
            yield Static("[Tab] 切换登录/注册  [Esc] 返回", id="help-label")

    def on_mount(self) -> None:
        self._update_mode()
        self.query_one("#email-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            self._do_login()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_login()

    def action_toggle_mode(self) -> None:
        self._is_register = not self._is_register
        self._update_mode()

    def action_cycle_role(self) -> None:
        if self._is_register:
            self.cycle_role()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_try_login(self) -> None:
        self._do_login()

    def _update_mode(self) -> None:
        try:
            mode_label = self.query_one("#mode-label", Static)
            submit_btn = self.query_one("#submit-btn", Button)
            confirm_input = self.query_one("#confirm-input", Input)
            role_label = self.query_one("#role-label", Static)

            if self._is_register:
                mode_label.update("📝 注册")
                submit_btn.label = "注册"
                confirm_input.display = True
                role_label.display = True
                self._update_role_label()
            else:
                mode_label.update("🔐 登录")
                submit_btn.label = "登录"
                confirm_input.display = False
                role_label.display = False
        except Exception:
            pass

    def _do_login(self) -> None:
        email = self.query_one("#email-input", Input).value.strip()
        password = self.query_one("#password-input", Input).value.strip()
        error_label = self.query_one("#error-label", Static)

        if not email or not password:
            error_label.update("邮箱和密码不能为空")
            return

        if self._is_register:
            confirm = self.query_one("#confirm-input", Input).value.strip()
            if password != confirm:
                error_label.update("两次密码不一致")
                return

        error_label.update("登录中...")
        self.query_one("#submit-btn", Button).disabled = True
        self._login_worker(email, password)

    @work(exclusive=True)
    async def _login_worker(self, email: str, password: str) -> None:
        import asyncio
        from ...auth import AuthenticationError
        from ...http_client import APIError

        error_label = self.query_one("#error-label", Static)
        submit_btn = self.query_one("#submit-btn", Button)

        try:
            auth = self._auth or AuthModule()
            client = AgentHubClient(base_url=self._api_base_url, auth=auth)

            if self._is_register:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.register_user(email, password)
                )
                token = result.get("access_token", "")
                if token:
                    auth.save_token(token)
                role = ROLES[self._role_idx]
                agent_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: client.register_agent(
                        name=f"agent-{email.split('@')[0]}",
                        model_name="claude-3.5-sonnet",
                        role=role,
                        jwt_token=token,
                    ),
                )
                if agent_result:
                    agent_id = agent_result.get("id", "")
                    api_key = agent_result.get("api_key", "")
                    result_role = agent_result.get("role", role)
                    name = agent_result.get("name", f"agent-{email.split('@')[0]}")
                    if api_key:
                        auth.save_agent_key(api_key)
                    if agent_id:
                        auth.save_agent_info(agent_id=agent_id, name=name, role=result_role)
            else:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.login_user(email, password)
                )
                token = result.get("access_token", "")
                if token:
                    auth.save_token(token)

            error_label.update("✅ 登录成功！")

            try:
                from ..app import AgentHubTUI
                main_app = self.app
                if isinstance(main_app, AgentHubTUI):
                    main_app._auth = auth
                    config = load_config()
                    main_app._client = AgentHubClient(
                        base_url=main_app._api_base_url or config.api_base_url,
                        auth=auth,
                    )
                    agent_info = AuthModule.AGENT_INFO_PATH
                    if agent_info.exists():
                        import json as _json
                        info = _json.loads(agent_info.read_text(encoding="utf-8"))
                        main_app._agent_id = info.get("agent_id", main_app._agent_id)
                        main_app._role = info.get("role", main_app._role)
                    status_bar = main_app.query_one("#status-bar")
                    status_bar.set_agent_info(
                        main_app._agent_id or "unknown",
                        main_app._role or "unknown",
                    )
                    main_app._refresh_tasks()
                    main_app._load_repos()
            except Exception:
                pass

            self.app.pop_screen()

        except AuthenticationError as e:
            error_label.update(f"❌ 认证失败: {e}")
        except APIError as e:
            error_label.update(f"❌ 错误 {e.status_code}: {e.message}")
        except Exception as e:
            error_label.update(f"❌ 错误: {e}")
        finally:
            submit_btn.disabled = False
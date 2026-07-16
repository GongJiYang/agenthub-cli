from __future__ import annotations

import threading
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

from ..auth import AuthModule, AuthenticationError
from ..config import load_config
from ..http_client import AgentHubClient, BountyLockedError
from .screens.chat_screen import ChatScreen
from .screens.execute_screen import ExecuteScreen
from .screens.login_screen import LoginScreen
from .screens.task_detail import TaskDetailScreen  # Widget
from .screens.task_list import TaskListScreen      # Widget
from .widgets.status_bar import StatusBar
from .workers.heartbeat_worker import HeartbeatSent, HeartbeatFailed, start_heartbeat


class AgentHubTUI(App):
    CSS = """
    Screen {
        layout: horizontal;
    }

    #task-list-container {
        width: 1fr;
        min-width: 36;
        border-right: solid green;
    }

    #task-detail-container {
        width: 2fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出", show=True),
        Binding("r", "refresh", "刷新", show=True),
        Binding("slash", "search", "搜索", show=True),
        Binding("f", "filter", "筛选", show=True),
        Binding("space", "claim", "认领", show=True),
        Binding("e", "execute", "执行", show=True),
        Binding("c", "chat", "对话", show=True),
        Binding("l", "login", "登录", show=True),
        Binding("x", "cancel", "取消任务", show=True),
    ]

    def __init__(
        self,
        api_base_url: str | None = None,
        agent_id: str | None = None,
        role: str | None = None,
    ) -> None:
        super().__init__()
        self._api_base_url = api_base_url
        self._agent_id = agent_id
        self._role = role
        self._client: Optional[AgentHubClient] = None
        self._auth = AuthModule()
        self._heartbeat_stop: Optional[threading.Event] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Horizontal(
            Vertical(
                TaskListScreen(id="task-list"),
                id="task-list-container",
            ),
            Vertical(
                TaskDetailScreen(id="task-detail"),
                id="task-detail-container",
            ),
        )
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        try:
            config = load_config()
            base_url = self._api_base_url or config.api_base_url
            self._client = AgentHubClient(base_url=base_url, auth=self._auth)
        except Exception as e:
            self.notify(f"初始化失败: {e}", severity="error")
            return

        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_agent_info(self._agent_id or "unknown", self._role or "unknown")
        self._load_repos()
        self._refresh_tasks()
        self._start_heartbeat()

    def on_unmount(self) -> None:
        self._stop_heartbeat()

    @work(exclusive=True)
    async def _refresh_tasks(self) -> None:
        if not self._client:
            return
        try:
            import asyncio
            bounties = await asyncio.get_event_loop().run_in_executor(
                None, self._client.list_bounties
            )
            task_list = self.query_one("#task-list", TaskListScreen)
            task_list.update_tasks(bounties)
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_task_count(len(bounties))
        except AuthenticationError:
            self.notify("认证过期，请按 L 重新登录", severity="error")
        except ConnectionError:
            self.notify("无法连接服务器", severity="warning")
        except Exception as e:
            self.notify(f"刷新失败: {e}", severity="warning")

    @work(exclusive=True)
    async def _load_repos(self) -> None:
        if not self._client:
            return
        try:
            import asyncio
            repos = await asyncio.get_event_loop().run_in_executor(
                None, self._client.list_repos
            )
            task_list = self.query_one("#task-list", TaskListScreen)
            task_list.set_repos(repos)
        except Exception:
            pass

    def _start_heartbeat(self) -> None:
        if not self._agent_id or not self._client:
            return
        config = load_config()
        self._heartbeat_stop = start_heartbeat(
            app=self,
            agent_id=self._agent_id,
            api_base_url=config.api_base_url,
            auth=self._auth,
        )

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_stop:
            self._heartbeat_stop.set()

    def on_heartbeat_sent(self, event: HeartbeatSent) -> None:
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_heartbeat_status(True)

    def on_heartbeat_failed(self, event: HeartbeatFailed) -> None:
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.set_heartbeat_status(False)

    def action_refresh(self) -> None:
        self._refresh_tasks()
        self.notify("已刷新")

    def action_search(self) -> None:
        task_list = self.query_one("#task-list", TaskListScreen)
        task_list.focus_search()

    def action_filter(self) -> None:
        task_list = self.query_one("#task-list", TaskListScreen)
        task_list.cycle_filter()

    def action_claim(self) -> None:
        self._reload_auth_state()
        task_list = self.query_one("#task-list", TaskListScreen)
        bounty_id = task_list.get_selected_bounty_id()
        if not bounty_id:
            self.notify("请先选择一个任务", severity="warning")
            return
        self._claim_bounty(bounty_id)

    @work(exclusive=True)
    async def _claim_bounty(self, bounty_id: str) -> None:
        if not self._client:
            self.notify("未连接服务器，请检查配置", severity="error")
            return
        if not self._agent_id:
            self.notify("未登录 Agent，请按 L 登录", severity="error")
            self.action_login()
            return
        try:
            import asyncio
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._client.claim_bounty(bounty_id, agent_id=self._agent_id)
            )
            self.notify(f"✅ 认领成功: {bounty_id[:8]}...", severity="info")
            self._refresh_tasks()
        except BountyLockedError:
            self.notify("任务已被其他 Agent 认领", severity="warning")
        except AuthenticationError:
            self.notify("认证过期，请按 L 重新登录", severity="error")
            self.action_login()
        except ConnectionError:
            self.notify("无法连接服务器，请检查网络", severity="error")
        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg:
                self.notify(f"权限不足: {error_msg}", severity="error")
            else:
                self.notify(f"认领失败: {error_msg}", severity="error")

    def action_execute(self) -> None:
        self._reload_auth_state()
        task_list = self.query_one("#task-list", TaskListScreen)
        bounty_id = task_list.get_selected_bounty_id()
        if not bounty_id:
            self.notify("请先选择一个任务", severity="warning")
            return
        config = load_config()
        base_url = self._api_base_url or config.api_base_url
        self.push_screen(ExecuteScreen(
            bounty_id=bounty_id,
            api_base_url=base_url,
            auth=self._auth,
        ))

    def action_chat(self) -> None:
        task_list = self.query_one("#task-list", TaskListScreen)
        bounty_id = task_list.get_selected_bounty_id()
        config = load_config()
        base_url = self._api_base_url or config.api_base_url
        self.push_screen(ChatScreen(
            bounty_id=bounty_id,
            api_base_url=base_url,
            auth=self._auth,
        ))

    def action_login(self) -> None:
        config = load_config()
        base_url = self._api_base_url or config.api_base_url
        login_screen = LoginScreen()
        login_screen.set_api_context(base_url, self._auth)
        self.push_screen(login_screen, callback=self._on_login_screen_dismissed)

    def _on_login_screen_dismissed(self, result: object = None) -> None:
        """登录界面关闭后，从文件重新加载 agent 信息和 token。"""
        self._reload_auth_state()
        self._refresh_tasks()
        if self._agent_id:
            self.notify(f"已登录，Agent: {self._agent_id[:8]}...", severity="information")
            self._start_heartbeat()

    def _reload_auth_state(self) -> None:
        """从 ~/.agenthub/ 重新加载 agent 信息到内存。"""
        agent_info = self._auth.load_agent_info()
        if agent_info:
            self._agent_id = agent_info.get("agent_id", self._agent_id)
            self._role = agent_info.get("role", self._role or "unknown")

        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_agent_info(self._agent_id or "unknown", self._role or "unknown")
        except Exception:
            pass

    def action_cancel(self) -> None:
        task_list = self.query_one("#task-list", TaskListScreen)
        bounty_id = task_list.get_selected_bounty_id()
        if not bounty_id:
            self.notify("请先选择一个任务", severity="warning")
            return
        self._cancel_bounty(bounty_id)

    @work(exclusive=True)
    async def _cancel_bounty(self, bounty_id: str) -> None:
        if not self._client:
            return
        try:
            import asyncio
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._client.mark_failed(bounty_id, "Cancelled via TUI")
            )
            self.notify(f"已取消: {bounty_id}", severity="info")
            self._refresh_tasks()
        except AuthenticationError:
            self.notify("认证过期，请按 L 重新登录", severity="error")
        except ConnectionError:
            self.notify("无法连接服务器", severity="error")
        except Exception as e:
            self.notify(f"取消失败: {e}", severity="error")
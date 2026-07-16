from agenthub.tui.screens.execute_screen import ExecuteScreen
from agenthub.tui.screens.chat_screen import ChatScreen
from agenthub.tui.app import AgentHubTUI


def test_execute_screen_instantiable():
    screen = ExecuteScreen(bounty_id="test-123", api_base_url="http://localhost:8000/api/v1", auth=None)
    assert screen is not None
    assert screen._bounty_id == "test-123"
    assert screen._executing is False
    assert screen._completed is False


def test_execute_screen_cancel_flag():
    screen = ExecuteScreen(bounty_id="test-123", api_base_url="http://localhost:8000/api/v1", auth=None)
    assert not screen._cancel_flag.is_set()
    screen._cancel_flag.set()
    assert screen._cancel_flag.is_set()


def test_chat_screen_instantiable():
    screen = ChatScreen()
    assert screen is not None


def test_chat_screen_with_bounty():
    screen = ChatScreen(bounty_id="bounty-456", api_base_url="http://localhost:8000/api/v1", auth=None)
    assert screen._bounty_id == "bounty-456"


def test_chat_screen_handle_exit_command():
    screen = ChatScreen()
    assert hasattr(screen, "action_exit_chat")


def test_app_bindings_include_new_keys():
    new_bindings = {b.key for b in AgentHubTUI.BINDINGS}
    assert "e" in new_bindings
    assert "c" in new_bindings
    assert "l" in new_bindings
    assert "x" in new_bindings


def test_app_bindings_preserve_existing_keys():
    new_bindings = {b.key for b in AgentHubTUI.BINDINGS}
    assert "q" in new_bindings
    assert "r" in new_bindings
    assert "f" in new_bindings
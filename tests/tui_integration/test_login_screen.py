from agenthub.tui.screens.login_screen import LoginScreen


def test_login_screen_instantiable():
    screen = LoginScreen()
    assert screen is not None


def test_login_screen_default_mode():
    screen = LoginScreen()
    assert screen._is_register is False


def test_login_screen_toggle_mode():
    screen = LoginScreen()
    screen._is_register = True
    assert screen._is_register is True
    screen._is_register = False
    assert screen._is_register is False


def test_login_screen_set_api_context():
    screen = LoginScreen()
    screen.set_api_context("http://localhost:8000/api/v1", auth=None)
    assert screen._api_base_url == "http://localhost:8000/api/v1"
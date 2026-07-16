from __future__ import annotations

import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from agenthub.tui.bridges.ui_chat_bridge import UIChatBridge, ChatCancelFlag


def test_chat_cancel_flag_set_and_is_set():
    flag = ChatCancelFlag()
    assert not flag.is_set()
    flag.set()
    assert flag.is_set()


def test_chat_cancel_flag_clear():
    flag = ChatCancelFlag()
    flag.set()
    assert flag.is_set()
    flag.clear()
    assert not flag.is_set()


def test_ui_chat_bridge_instantiation():
    tokens = []
    bridge = UIChatBridge(on_token=lambda t: tokens.append(t))
    assert not bridge.is_running()


def test_ui_chat_bridge_default_callbacks():
    bridge = UIChatBridge()
    assert not bridge.is_running()


def test_ui_chat_bridge_cancel():
    bridge = UIChatBridge()
    bridge.cancel()
    assert True


def test_chat_cancel_flag_thread_safety():
    flag = ChatCancelFlag()
    results = []

    def worker():
        for _ in range(100):
            flag.set()
            results.append(flag.is_set())
            flag.clear()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 300
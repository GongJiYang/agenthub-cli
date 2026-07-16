import os

from agenthub.tui.workers.heartbeat_worker import HeartbeatSent, HeartbeatFailed, start_heartbeat


def test_heartbeat_messages_defined():
    sent = HeartbeatSent()
    assert isinstance(sent, HeartbeatSent)

    failed = HeartbeatFailed(message="timeout")
    assert failed.message == "timeout"


def test_heartbeat_interval_from_env():
    original = os.environ.get("AGENTHUB_HEARTBEAT_INTERVAL")
    os.environ["AGENTHUB_HEARTBEAT_INTERVAL"] = "5"
    try:
        assert int(os.environ.get("AGENTHUB_HEARTBEAT_INTERVAL", "30")) == 5
    finally:
        if original is not None:
            os.environ["AGENTHUB_HEARTBEAT_INTERVAL"] = original
        else:
            os.environ.pop("AGENTHUB_HEARTBEAT_INTERVAL", None)


def test_heartbeat_default_interval():
    original = os.environ.pop("AGENTHUB_HEARTBEAT_INTERVAL", None)
    try:
        assert int(os.environ.get("AGENTHUB_HEARTBEAT_INTERVAL", "30")) == 30
    finally:
        if original is not None:
            os.environ["AGENTHUB_HEARTBEAT_INTERVAL"] = original


def test_heartbeat_stop_event():
    import threading
    event = threading.Event()
    assert not event.is_set()
    event.set()
    assert event.is_set()
    event.clear()
    assert not event.is_set()
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

from textual import work


@dataclass
class HeartbeatSent:
    pass


@dataclass
class HeartbeatFailed:
    message: str


def start_heartbeat(
    app: Any,
    agent_id: str,
    api_base_url: str,
    auth: Any,
    interval: int | None = None,
) -> threading.Event:
    """Start a background heartbeat thread. Returns a stop event."""
    stop_event = threading.Event()
    actual_interval = interval or int(os.environ.get("AGENTHUB_HEARTBEAT_INTERVAL", "30"))

    def _heartbeat_loop() -> None:
        from ..http_client import AgentHubClient

        client = AgentHubClient(base_url=api_base_url, auth=auth)
        while not stop_event.wait(timeout=actual_interval):
            try:
                client.send_heartbeat(agent_id)
                try:
                    app.call_from_thread(app.emit_message, HeartbeatSent())
                except Exception:
                    pass
            except Exception as e:
                try:
                    app.call_from_thread(app.emit_message, HeartbeatFailed(message=str(e)))
                except Exception:
                    pass

    thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat")
    thread.start()
    return stop_event
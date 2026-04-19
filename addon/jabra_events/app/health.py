from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class Health:
    started_at: float = field(default_factory=time.time)
    last_graph_auth_ok: float | None = None
    last_calendar_poll_ok: float | None = None
    last_calendar_poll_error: str | None = None
    active_subscriptions: int = 0
    next_subscription_renewal: float | None = None
    ws_connected: bool = False
    last_forwarded_event_at: float | None = None
    last_triggered_mode: str | None = None
    last_triggered_at: float | None = None
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def update(self, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self.started_at,
                "uptime_seconds": time.time() - self.started_at,
                "last_graph_auth_ok": self.last_graph_auth_ok,
                "last_calendar_poll_ok": self.last_calendar_poll_ok,
                "last_calendar_poll_error": self.last_calendar_poll_error,
                "active_subscriptions": self.active_subscriptions,
                "next_subscription_renewal": self.next_subscription_renewal,
                "ws_connected": self.ws_connected,
                "last_forwarded_event_at": self.last_forwarded_event_at,
                "last_triggered_mode": self.last_triggered_mode,
                "last_triggered_at": self.last_triggered_at,
            }

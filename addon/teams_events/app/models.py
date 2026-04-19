from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class RoomConfig:
    room_id: str
    account_email: str
    mode_id: str


@dataclass(frozen=True)
class AppConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    relay_ws_url: str
    relay_token: str
    graph_webhook_url: str
    site_id: str
    ha_base_url: str
    ha_token: str
    poll_interval_seconds: int
    meeting_lookahead_minutes: int
    dedupe_window_seconds: int
    subscription_lifetime_minutes: int
    renewal_headroom_minutes: int
    subscription_state_path: str
    trigger_modes: bool
    log_level: str
    rooms: tuple[RoomConfig, ...]

    def room_by_email(self, email: str) -> Optional[RoomConfig]:
        lower = email.lower()
        return next((r for r in self.rooms if r.account_email.lower() == lower), None)


@dataclass
class MeetingWatch:
    room: RoomConfig
    meeting_id: str
    join_web_url: str
    start: datetime
    end: datetime


@dataclass
class SubscriptionRecord:
    subscription_id: str
    room: RoomConfig
    meeting_id: str
    join_web_url: str
    expires_at: datetime
    client_state: str = field(default="")

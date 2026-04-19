from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AppConfig, RoomConfig

DEFAULT_OPTIONS_PATHS = (
    Path("/data/options.json"),
    Path("options.json"),
)


def _load_options(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text())
    for candidate in DEFAULT_OPTIONS_PATHS:
        if candidate.exists():
            return json.loads(candidate.read_text())
    raise FileNotFoundError(
        f"No options file found (looked in {', '.join(str(p) for p in DEFAULT_OPTIONS_PATHS)})"
    )


def _ha_token() -> str:
    # The Supervisor provides SUPERVISOR_TOKEN for hassio_api calls; for calling
    # the HA core API from inside an add-on, the same token works against
    # http://supervisor/core/api.
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN") or ""
    return token


def load_config(path: Path | None = None) -> AppConfig:
    raw = _load_options(path)
    rooms = tuple(
        RoomConfig(
            room_id=r["room_id"],
            account_email=r["account_email"],
            mode_id=r["mode_id"],
        )
        for r in raw.get("rooms", [])
    )
    return AppConfig(
        tenant_id=raw.get("tenant_id", ""),
        client_id=raw.get("client_id", ""),
        client_secret=raw.get("client_secret", ""),
        relay_ws_url=raw["relay_ws_url"],
        relay_token=raw.get("relay_token", ""),
        graph_webhook_url=raw.get("graph_webhook_url", ""),
        site_id=raw.get("site_id", "office-ha"),
        ha_base_url=raw.get("ha_base_url", "http://supervisor/core"),
        ha_token=_ha_token(),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 30)),
        meeting_lookahead_minutes=int(raw.get("meeting_lookahead_minutes", 15)),
        dedupe_window_seconds=int(raw.get("dedupe_window_seconds", 20)),
        subscription_lifetime_minutes=int(raw.get("subscription_lifetime_minutes", 55)),
        renewal_headroom_minutes=int(raw.get("renewal_headroom_minutes", 15)),
        subscription_state_path=raw.get("subscription_state_path", "/data/subscriptions.json"),
        trigger_modes=bool(raw.get("trigger_modes", True)),
        log_level=raw.get("log_level", "INFO"),
        rooms=rooms,
    )

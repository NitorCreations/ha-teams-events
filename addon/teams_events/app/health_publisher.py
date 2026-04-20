from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .ha_client import HAClient
from .health import Health

log = logging.getLogger(__name__)

ATTRIBUTION = "via ha-teams-events add-on"


class HealthPublisher:
    """Publishes `Health` snapshots to Home Assistant as state-pushed sensors.

    Uses the HA REST API `POST /api/states/<entity_id>` endpoint. These
    entities don't exist in the entity registry — HA keeps whatever the last
    push set them to. When the add-on stops, they stay at their last value;
    `last_update_at` on each state tells the user when the value was fresh.
    """

    ENTITY_RELAY_CONNECTED = "binary_sensor.teams_events_relay_connected"
    ENTITY_ACTIVE_SUBS = "sensor.teams_events_active_subscriptions"
    ENTITY_NEXT_RENEWAL = "sensor.teams_events_next_subscription_renewal"
    ENTITY_LAST_GRAPH_AUTH = "sensor.teams_events_last_graph_auth"
    ENTITY_LAST_POLL = "sensor.teams_events_last_calendar_poll"
    ENTITY_LAST_EVENT = "sensor.teams_events_last_forwarded_event"
    ENTITY_LAST_MODE = "sensor.teams_events_last_triggered_mode"

    def __init__(
        self,
        ha: HAClient,
        health: Health,
        interval_seconds: int = 30,
    ) -> None:
        self._ha = ha
        self._health = health
        self._interval = interval_seconds

    async def run(self) -> None:
        while True:
            try:
                await self._publish_once()
            except Exception as exc:  # pragma: no cover - top-level safety
                log.warning("Health publish failed: %s", exc)
            await asyncio.sleep(self._interval)

    async def _publish_once(self) -> None:
        snap = self._health.snapshot()

        await self._set(
            self.ENTITY_RELAY_CONNECTED,
            "on" if snap["ws_connected"] else "off",
            {
                "friendly_name": "Teams Events relay connected",
                "icon": "mdi:transit-connection-variant",
                "device_class": "connectivity",
            },
        )

        await self._set(
            self.ENTITY_ACTIVE_SUBS,
            snap["active_subscriptions"],
            {
                "friendly_name": "Teams Events active subscriptions",
                "icon": "mdi:calendar-sync",
                "state_class": "measurement",
            },
        )

        await self._set_timestamp(
            self.ENTITY_NEXT_RENEWAL,
            snap["next_subscription_renewal"],
            "Teams Events next subscription renewal",
            "mdi:calendar-clock",
        )

        await self._set_timestamp(
            self.ENTITY_LAST_GRAPH_AUTH,
            snap["last_graph_auth_ok"],
            "Teams Events last Graph auth",
            "mdi:key-chain",
        )

        await self._set_timestamp(
            self.ENTITY_LAST_POLL,
            snap["last_calendar_poll_ok"],
            "Teams Events last calendar poll",
            "mdi:calendar-refresh",
            extra_attrs={"last_error": snap.get("last_calendar_poll_error")},
        )

        await self._set_timestamp(
            self.ENTITY_LAST_EVENT,
            snap["last_forwarded_event_at"],
            "Teams Events last forwarded event",
            "mdi:microsoft-teams",
        )

        mode = snap.get("last_triggered_mode")
        await self._set(
            self.ENTITY_LAST_MODE,
            mode if mode is not None else "unknown",
            {
                "friendly_name": "Teams Events last triggered mode",
                "icon": "mdi:auto-mode",
                "last_triggered_at": _ts(snap.get("last_triggered_at")),
            },
        )

    async def _set_timestamp(
        self,
        entity_id: str,
        epoch: float | None,
        friendly_name: str,
        icon: str,
        extra_attrs: dict[str, Any] | None = None,
    ) -> None:
        state = _ts(epoch)
        attrs: dict[str, Any] = {
            "friendly_name": friendly_name,
            "icon": icon,
        }
        if state != "unknown":
            attrs["device_class"] = "timestamp"
        if extra_attrs:
            attrs.update({k: v for k, v in extra_attrs.items() if v is not None})
        await self._set(entity_id, state, attrs)

    async def _set(
        self, entity_id: str, state: Any, attributes: dict[str, Any]
    ) -> None:
        attributes = {**attributes, "attribution": ATTRIBUTION}
        try:
            await self._ha.set_state(entity_id, state, attributes)
        except Exception as exc:
            log.debug("set_state failed for %s: %s", entity_id, exc)


def _ts(epoch: float | None) -> str:
    if epoch is None:
        return "unknown"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .ha_client import HAClient
from .health import Health
from .subscription_store import SubscriptionStore

log = logging.getLogger(__name__)


class EventRouter:
    """Routes Graph notifications (forwarded by the relay) to room_modes.run_mode.

    For each notification we look up the stored subscription, verify the
    `clientState` matches the secret we set at creation time, dedupe within a
    short window, and trigger the room mode.
    """

    def __init__(
        self,
        store: SubscriptionStore,
        ha: HAClient,
        health: Health,
        dedupe_window_seconds: int,
        trigger_modes: bool = True,
    ) -> None:
        self._store = store
        self._ha = ha
        self._health = health
        self._dedupe_window = dedupe_window_seconds
        self._trigger_modes = trigger_modes
        self._last_fire: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def handle(self, message: dict[str, Any]) -> None:
        if message.get("type") != "graph_notification":
            log.debug("Ignoring non-notification message: %s", message.get("type"))
            return
        payload = message.get("payload") or {}
        notifications = payload.get("value") or []
        for notification in notifications:
            await self._handle_one(notification)

    async def _handle_one(self, notification: dict[str, Any]) -> None:
        subscription_id = notification.get("subscriptionId")
        if not subscription_id:
            log.warning("Notification missing subscriptionId: %s", notification)
            return
        record = self._store.by_subscription_id(subscription_id)
        if record is None:
            log.info("No local mapping for subscription %s; ignoring", subscription_id)
            return
        incoming_state = notification.get("clientState", "")
        if record.client_state and incoming_state != record.client_state:
            log.warning(
                "Rejecting notification for subscription %s: clientState mismatch",
                subscription_id,
            )
            return
        self._health.update(last_forwarded_event_at=time.time())

        async with self._lock:
            last = self._last_fire.get(record.room.room_id, 0.0)
            now = time.time()
            if now - last < self._dedupe_window:
                log.info(
                    "Debouncing notification for room %s (%.1fs since last)",
                    record.room.room_id,
                    now - last,
                )
                return
            self._last_fire[record.room.room_id] = now

        log.info(
            "Teams event matched: room=%s mode=%s meeting=%s",
            record.room.room_id,
            record.room.mode_id,
            record.meeting_id,
        )
        if not self._trigger_modes:
            return
        try:
            await self._ha.run_room_mode(record.room.mode_id)
            self._health.update(
                last_triggered_mode=record.room.mode_id,
                last_triggered_at=time.time(),
            )
        except Exception as exc:  # pragma: no cover
            log.exception("run_room_mode failed: %s", exc)

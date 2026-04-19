from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .cert_store import NotificationCert
from .ha_client import HAClient
from .health import Health
from .notification_decrypt import DecryptionError, decrypt_encrypted_content
from .subscription_store import SubscriptionStore

log = logging.getLogger(__name__)


class EventRouter:
    """Routes Graph notifications (forwarded by the relay) to room_modes.run_mode.

    For each notification we look up the stored subscription, verify the
    `clientState` matches the secret we set at creation time, optionally
    decrypt the resource data, dedupe within a short window, and trigger the
    room mode.

    We currently treat any notification targeting a known subscription as a
    trigger signal. The subscription was created for exactly one meeting and
    the dedupe window suppresses burst notifications, so this works for the
    "Jabra joins the call" signal without having to inspect participant lists.
    The decrypted payload is still logged at INFO for observability.
    """

    def __init__(
        self,
        store: SubscriptionStore,
        ha: HAClient,
        health: Health,
        dedupe_window_seconds: int,
        cert: NotificationCert,
        trigger_modes: bool = True,
    ) -> None:
        self._store = store
        self._ha = ha
        self._health = health
        self._dedupe_window = dedupe_window_seconds
        self._cert = cert
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

        encrypted = notification.get("encryptedContent")
        if encrypted:
            try:
                decrypted = decrypt_encrypted_content(encrypted, self._cert)
                log.info(
                    "Decrypted meeting-call event for room %s: %s",
                    record.room.room_id,
                    _summarise(decrypted),
                )
            except DecryptionError as exc:
                log.warning(
                    "Failed to decrypt notification for subscription %s: %s",
                    subscription_id,
                    exc,
                )

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


def _summarise(payload: dict[str, Any]) -> str:
    """Single-line summary of a decrypted meetingCallEvents payload for logs."""
    keys = [
        k
        for k in (
            "callStartDateTime",
            "callEndDateTime",
            "eventDateTime",
            "eventType",
            "participantId",
        )
        if k in payload
    ]
    if keys:
        return ", ".join(f"{k}={payload[k]}" for k in keys)
    return ",".join(sorted(payload.keys()))[:200]

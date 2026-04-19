from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from dateutil import parser as dtparse

from .cert_store import NotificationCert
from .graph_client import GraphAuthError, GraphClient
from .health import Health
from .models import MeetingWatch, RoomConfig, SubscriptionRecord
from .subscription_store import SubscriptionStore

log = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages Graph change-notification subscriptions on Teams online meetings.

    For each watched meeting we subscribe to the `meetingCallEvents` resource
    keyed by the meeting's `joinWebUrl` — no meeting-id resolution step
    required. Rich notifications with encrypted resource data are enabled so
    we get participant/delta information directly in the notification.

    Reference:
      https://learn.microsoft.com/graph/changenotifications-for-onlinemeeting
    """

    def __init__(
        self,
        graph: GraphClient,
        store: SubscriptionStore,
        health: Health,
        notification_url: str,
        cert: NotificationCert,
        change_type: str = "updated",
        subscription_lifetime_minutes: int = 55,
        renewal_headroom_minutes: int = 15,
        renewal_check_seconds: int = 60,
    ) -> None:
        self._graph = graph
        self._store = store
        self._health = health
        self._notification_url = notification_url
        self._cert = cert
        self._change_type = change_type
        self._lifetime = timedelta(minutes=subscription_lifetime_minutes)
        self._renewal_headroom = timedelta(minutes=renewal_headroom_minutes)
        self._renewal_check = renewal_check_seconds
        self._lock = asyncio.Lock()

    # --- callback from CalendarWatcher -----------------------------------

    async def on_meeting_change(
        self, meeting: Optional[MeetingWatch], room: RoomConfig
    ) -> None:
        async with self._lock:
            existing = self._existing_for_room(room)
            if meeting is None:
                if existing is not None:
                    await self._delete(existing)
                return
            if existing is not None and existing.meeting_id == meeting.meeting_id:
                return
            if existing is not None:
                await self._delete(existing)
            try:
                await self._create(meeting)
            except GraphAuthError as exc:
                log.error(
                    "Failed to create subscription for %s/%s: %s",
                    room.room_id,
                    meeting.meeting_id,
                    exc,
                )

    # --- renewal loop ----------------------------------------------------

    async def run_renewal_loop(self) -> None:
        while True:
            try:
                await self._renew_due()
            except Exception as exc:  # pragma: no cover - top-level safety
                log.exception("Renewal loop iteration failed: %s", exc)
            self._update_health()
            await asyncio.sleep(self._renewal_check)

    async def _renew_due(self) -> None:
        deadline = datetime.now(timezone.utc) + self._renewal_headroom
        async with self._lock:
            due = list(self._store.expiring_before(deadline))
            for record in due:
                try:
                    await self._renew(record)
                except GraphAuthError as exc:
                    log.warning(
                        "Renewal failed for subscription %s (%s); will recreate next poll",
                        record.subscription_id,
                        exc,
                    )
                    self._store.remove(record.subscription_id)

    # --- shutdown --------------------------------------------------------

    async def cleanup_all(self) -> None:
        async with self._lock:
            records = self._store.all()
        for record in records:
            try:
                await self._graph.delete(f"/subscriptions/{record.subscription_id}")
            except GraphAuthError as exc:
                log.warning("Cleanup delete failed for %s: %s", record.subscription_id, exc)
            async with self._lock:
                self._store.remove(record.subscription_id)

    # --- internal --------------------------------------------------------

    def _existing_for_room(self, room: RoomConfig) -> Optional[SubscriptionRecord]:
        return next(
            (r for r in self._store.all() if r.room.room_id == room.room_id),
            None,
        )

    async def _create(self, meeting: MeetingWatch) -> SubscriptionRecord:
        resource = _meeting_call_events_resource(meeting.join_web_url)
        expires = datetime.now(timezone.utc) + self._lifetime
        client_state = secrets.token_urlsafe(32)
        body = {
            "changeType": self._change_type,
            "notificationUrl": self._notification_url,
            "resource": resource,
            "expirationDateTime": _graph_timestamp(expires),
            "clientState": client_state,
            "includeResourceData": True,
            "encryptionCertificate": self._cert.public_cert_b64_der,
            "encryptionCertificateId": self._cert.cert_id,
        }
        payload = await self._graph.post("/subscriptions", body)
        subscription_id = payload["id"]
        record = SubscriptionRecord(
            subscription_id=subscription_id,
            room=meeting.room,
            meeting_id=meeting.meeting_id,
            join_web_url=meeting.join_web_url,
            expires_at=dtparse.isoparse(payload["expirationDateTime"]),
            client_state=client_state,
        )
        self._store.upsert(record)
        log.info(
            "Created subscription %s for room=%s meeting=%s (expires %s)",
            subscription_id,
            meeting.room.room_id,
            meeting.meeting_id,
            record.expires_at.isoformat(),
        )
        self._update_health()
        return record

    async def _renew(self, record: SubscriptionRecord) -> SubscriptionRecord:
        expires = datetime.now(timezone.utc) + self._lifetime
        payload = await self._graph.patch(
            f"/subscriptions/{record.subscription_id}",
            {"expirationDateTime": _graph_timestamp(expires)},
        )
        new_expiry = dtparse.isoparse(payload["expirationDateTime"])
        renewed = SubscriptionRecord(
            subscription_id=record.subscription_id,
            room=record.room,
            meeting_id=record.meeting_id,
            join_web_url=record.join_web_url,
            expires_at=new_expiry,
            client_state=record.client_state,
        )
        self._store.upsert(renewed)
        log.info(
            "Renewed subscription %s until %s",
            record.subscription_id,
            new_expiry.isoformat(),
        )
        return renewed

    async def _delete(self, record: SubscriptionRecord) -> None:
        try:
            await self._graph.delete(f"/subscriptions/{record.subscription_id}")
            log.info("Deleted subscription %s", record.subscription_id)
        except GraphAuthError as exc:
            log.warning(
                "Delete failed for subscription %s: %s (dropping from local store)",
                record.subscription_id,
                exc,
            )
        self._store.remove(record.subscription_id)
        self._update_health()

    def _update_health(self) -> None:
        self._health.update(
            active_subscriptions=self._store.size(),
            next_subscription_renewal=(
                self._store.next_expiry().timestamp()
                if self._store.next_expiry() is not None
                else None
            ),
        )


def _meeting_call_events_resource(join_web_url: str) -> str:
    """Build the Graph subscription `resource` string for Teams meeting call
    events.

    The `joinWebUrl` that Teams embeds in calendar events is already
    URL-encoded (contains `%3a`, `%40`, `%7b`, …). Graph requires the value to
    appear *double* URL-encoded inside the OData function call, so we apply
    `quote` once more here. See:
      https://learn.microsoft.com/graph/changenotifications-for-onlinemeeting
    """
    double_encoded = quote(join_web_url, safe="")
    return f"communications/onlineMeetings(joinWebUrl='{double_encoded}')/meetingCallEvents"


def _graph_timestamp(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S."
    ) + f"{when.microsecond // 1000:03d}Z"

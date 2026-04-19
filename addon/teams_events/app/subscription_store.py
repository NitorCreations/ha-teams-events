from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterable

from dateutil import parser as dtparse

from .models import RoomConfig, SubscriptionRecord

log = logging.getLogger(__name__)


class SubscriptionStore:
    """Subscription registry with optional JSON persistence.

    If `persist_path` is given, the store reads existing records on
    construction and writes atomically on every mutation. This lets the add-on
    survive restarts without orphaning subscriptions on the Graph side: on
    startup the records are available so the manager can DELETE any that no
    longer correspond to a watched meeting.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._by_subscription: dict[str, SubscriptionRecord] = {}
        self._by_meeting: dict[str, SubscriptionRecord] = {}
        self._lock = Lock()
        self._persist_path = persist_path
        if persist_path is not None:
            self._load()

    # --- public API ------------------------------------------------------

    def upsert(self, record: SubscriptionRecord) -> None:
        with self._lock:
            self._by_subscription[record.subscription_id] = record
            self._by_meeting[record.meeting_id] = record
            self._persist_locked()

    def remove(self, subscription_id: str) -> SubscriptionRecord | None:
        with self._lock:
            rec = self._by_subscription.pop(subscription_id, None)
            if rec is not None:
                self._by_meeting.pop(rec.meeting_id, None)
                self._persist_locked()
            return rec

    def by_subscription_id(self, subscription_id: str) -> SubscriptionRecord | None:
        with self._lock:
            return self._by_subscription.get(subscription_id)

    def by_meeting_id(self, meeting_id: str) -> SubscriptionRecord | None:
        with self._lock:
            return self._by_meeting.get(meeting_id)

    def all(self) -> list[SubscriptionRecord]:
        with self._lock:
            return list(self._by_subscription.values())

    def expiring_before(self, deadline: datetime) -> Iterable[SubscriptionRecord]:
        with self._lock:
            return [
                r for r in self._by_subscription.values() if r.expires_at <= deadline
            ]

    def size(self) -> int:
        with self._lock:
            return len(self._by_subscription)

    def next_expiry(self) -> datetime | None:
        with self._lock:
            if not self._by_subscription:
                return None
            return min(r.expires_at for r in self._by_subscription.values())

    # --- persistence -----------------------------------------------------

    def _persist_locked(self) -> None:
        if self._persist_path is None:
            return
        data = [_record_to_dict(r) for r in self._by_subscription.values()]
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(self._persist_path.parent),
            delete=False,
            suffix=".tmp",
        )
        try:
            json.dump(data, tmp, indent=2)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(self._persist_path)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def _load(self) -> None:
        assert self._persist_path is not None
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text())
        except json.JSONDecodeError as exc:
            log.warning("Subscription state at %s is corrupt: %s", self._persist_path, exc)
            return
        for entry in raw:
            try:
                record = _record_from_dict(entry)
            except (KeyError, ValueError) as exc:
                log.warning("Skipping malformed subscription record: %s", exc)
                continue
            self._by_subscription[record.subscription_id] = record
            self._by_meeting[record.meeting_id] = record
        log.info(
            "Loaded %d persisted subscription record(s) from %s",
            len(self._by_subscription),
            self._persist_path,
        )


def _record_to_dict(record: SubscriptionRecord) -> dict:
    return {
        "subscription_id": record.subscription_id,
        "room": {
            "room_id": record.room.room_id,
            "account_email": record.room.account_email,
            "mode_id": record.room.mode_id,
        },
        "meeting_id": record.meeting_id,
        "join_web_url": record.join_web_url,
        "expires_at": record.expires_at.astimezone(timezone.utc).isoformat(),
        "client_state": record.client_state,
    }


def _record_from_dict(entry: dict) -> SubscriptionRecord:
    room = RoomConfig(
        room_id=entry["room"]["room_id"],
        account_email=entry["room"]["account_email"],
        mode_id=entry["room"]["mode_id"],
    )
    return SubscriptionRecord(
        subscription_id=entry["subscription_id"],
        room=room,
        meeting_id=entry["meeting_id"],
        join_web_url=entry["join_web_url"],
        expires_at=dtparse.isoparse(entry["expires_at"]),
        client_state=entry.get("client_state", ""),
    )

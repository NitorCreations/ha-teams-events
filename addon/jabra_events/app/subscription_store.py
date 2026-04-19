from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Iterable

from .models import SubscriptionRecord

log = logging.getLogger(__name__)


class SubscriptionStore:
    """In-memory subscription registry. Persisting to /data is a TODO."""

    def __init__(self) -> None:
        self._by_subscription: dict[str, SubscriptionRecord] = {}
        self._by_meeting: dict[str, SubscriptionRecord] = {}
        self._lock = Lock()

    def upsert(self, record: SubscriptionRecord) -> None:
        with self._lock:
            self._by_subscription[record.subscription_id] = record
            self._by_meeting[record.meeting_id] = record

    def remove(self, subscription_id: str) -> SubscriptionRecord | None:
        with self._lock:
            rec = self._by_subscription.pop(subscription_id, None)
            if rec is not None:
                self._by_meeting.pop(rec.meeting_id, None)
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

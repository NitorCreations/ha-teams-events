from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Iterable

from dateutil import parser as dtparse

from .graph_client import GraphClient
from .health import Health
from .models import MeetingWatch, RoomConfig

log = logging.getLogger(__name__)

# Callback invoked when a room's active/imminent meeting changes.
MeetingCallback = Callable[[MeetingWatch | None, RoomConfig], Awaitable[None]]


class CalendarWatcher:
    def __init__(
        self,
        graph: GraphClient,
        rooms: Iterable[RoomConfig],
        poll_interval_seconds: int,
        lookahead_minutes: int,
        on_meeting_change: MeetingCallback,
        health: Health,
    ) -> None:
        self._graph = graph
        self._rooms = tuple(rooms)
        self._poll_interval = poll_interval_seconds
        self._lookahead = lookahead_minutes
        self._on_change = on_meeting_change
        self._health = health
        self._current: dict[str, MeetingWatch | None] = {r.room_id: None for r in self._rooms}

    async def run(self) -> None:
        while True:
            try:
                await self._poll_once()
                self._health.update(
                    last_calendar_poll_ok=asyncio.get_event_loop().time(),
                    last_calendar_poll_error=None,
                )
            except Exception as exc:  # pragma: no cover - top-level safety net
                log.exception("Calendar poll failed: %s", exc)
                self._health.update(last_calendar_poll_error=str(exc))
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        now = datetime.now(timezone.utc)
        end = now + timedelta(minutes=self._lookahead)
        for room in self._rooms:
            meeting = await self._find_meeting(room, now, end)
            previous = self._current.get(room.room_id)
            changed = (
                meeting is None
                and previous is not None
                or meeting is not None
                and (previous is None or previous.meeting_id != meeting.meeting_id)
            )
            if changed:
                self._current[room.room_id] = meeting
                log.info(
                    "Room %s meeting changed: %s",
                    room.room_id,
                    meeting.meeting_id if meeting else "<cleared>",
                )
                await self._on_change(meeting, room)

    async def _find_meeting(
        self, room: RoomConfig, window_start: datetime, window_end: datetime
    ) -> MeetingWatch | None:
        path = f"/users/{room.account_email}/calendarView"
        params = {
            "startDateTime": window_start.isoformat(),
            "endDateTime": window_end.isoformat(),
            "$select": "id,subject,start,end,isOnlineMeeting,onlineMeeting,onlineMeetingProvider",
            "$orderby": "start/dateTime",
            "$top": "5",
        }
        payload = await self._graph.get(path, params=params)
        for event in payload.get("value", []):
            if not event.get("isOnlineMeeting"):
                continue
            if event.get("onlineMeetingProvider") not in (
                "teamsForBusiness",
                "teams",
                None,
            ):
                continue
            join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
            if not join_url:
                continue
            return MeetingWatch(
                room=room,
                meeting_id=event["id"],
                join_web_url=join_url,
                start=dtparse.isoparse(event["start"]["dateTime"]).replace(
                    tzinfo=timezone.utc
                ),
                end=dtparse.isoparse(event["end"]["dateTime"]).replace(tzinfo=timezone.utc),
            )
        return None

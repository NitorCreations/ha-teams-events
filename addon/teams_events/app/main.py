from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import AsyncExitStack

import aiohttp

from .calendar_watcher import CalendarWatcher
from .config import load_config
from .event_router import EventRouter
from .graph_client import GraphClient
from .ha_client import HAClient
from .health import Health
from .models import MeetingWatch, RoomConfig
from .relay_ws_client import RelayWSClient
from .subscription_store import SubscriptionStore

log = logging.getLogger("teams_events")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


async def _amain() -> None:
    config = load_config()
    _configure_logging(config.log_level)
    log.info("Starting teams-events add-on (site=%s rooms=%d)", config.site_id, len(config.rooms))

    health = Health()
    store = SubscriptionStore()

    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(aiohttp.ClientSession())
        ha = HAClient(config.ha_base_url, config.ha_token, session)
        graph = GraphClient(
            config.tenant_id, config.client_id, config.client_secret, session
        )
        router = EventRouter(
            store=store,
            ha=ha,
            health=health,
            dedupe_window_seconds=config.dedupe_window_seconds,
            trigger_modes=False,
        )
        relay = RelayWSClient(
            url=config.relay_ws_url,
            site_id=config.site_id,
            token=config.relay_token,
            on_message=router.handle,
            health=health,
        )

        def on_meeting_change(meeting: MeetingWatch | None, room: RoomConfig) -> None:
            # Subscription management lands in Phase 3; for now we only log.
            if meeting is None:
                log.info("Room %s has no active/imminent meeting", room.room_id)
            else:
                log.info(
                    "Room %s: meeting %s (%s → %s) joinUrl=%s",
                    room.room_id,
                    meeting.meeting_id,
                    meeting.start.isoformat(),
                    meeting.end.isoformat(),
                    meeting.join_web_url,
                )

        watcher = CalendarWatcher(
            graph=graph,
            rooms=config.rooms,
            poll_interval_seconds=config.poll_interval_seconds,
            lookahead_minutes=config.meeting_lookahead_minutes,
            on_meeting_change=on_meeting_change,
            health=health,
        )

        tasks = [
            asyncio.create_task(relay.run(), name="relay-ws"),
        ]
        if config.tenant_id and config.client_id and config.client_secret:
            tasks.append(asyncio.create_task(watcher.run(), name="calendar-watcher"))
        else:
            log.warning("Graph credentials not configured; calendar watcher disabled")

        loop = asyncio.get_running_loop()
        stop = loop.create_future()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: stop.done() or stop.set_result(s))

        done, pending = await asyncio.wait(
            [*tasks, stop], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("Shutdown complete")


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

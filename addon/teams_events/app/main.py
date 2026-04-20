from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import AsyncExitStack
from pathlib import Path

import aiohttp

from .calendar_watcher import CalendarWatcher
from .cert_store import load_or_generate
from .config import load_config
from .event_router import EventRouter
from .graph_client import GraphClient
from .ha_client import HAClient
from .health import Health
from .health_publisher import HealthPublisher
from .relay_ws_client import RelayWSClient
from .subscription_manager import SubscriptionManager
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

    state_path = Path(config.subscription_state_path) if config.subscription_state_path else None
    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    store = SubscriptionStore(persist_path=state_path)

    cert = load_or_generate(
        Path(config.notification_cert_path), Path(config.notification_key_path)
    )
    log.info("Notification cert id (SHA-256 thumbprint): %s", cert.cert_id)

    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(aiohttp.ClientSession())
        ha = HAClient(config.ha_base_url, config.ha_token, session)
        graph = GraphClient(
            config.tenant_id,
            config.client_id,
            config.client_secret,
            session,
            health=health,
        )
        router = EventRouter(
            store=store,
            ha=ha,
            health=health,
            dedupe_window_seconds=config.dedupe_window_seconds,
            cert=cert,
            trigger_modes=config.trigger_modes,
        )
        relay = RelayWSClient(
            url=config.relay_ws_url,
            site_id=config.site_id,
            token=config.relay_token,
            on_message=router.handle,
            health=health,
        )

        graph_credentials_ok = bool(
            config.tenant_id and config.client_id and config.client_secret
        )

        subscription_manager: SubscriptionManager | None = None
        if graph_credentials_ok and config.graph_webhook_url:
            subscription_manager = SubscriptionManager(
                graph=graph,
                store=store,
                health=health,
                notification_url=config.graph_webhook_url,
                cert=cert,
                subscription_lifetime_minutes=config.subscription_lifetime_minutes,
                renewal_headroom_minutes=config.renewal_headroom_minutes,
            )
        elif graph_credentials_ok:
            log.warning(
                "graph_webhook_url is empty; subscription manager disabled"
            )

        async def on_meeting_change(meeting, room):
            if meeting is None:
                log.info("Room %s has no active/imminent meeting", room.room_id)
            else:
                log.info(
                    "Room %s: meeting %s (%s → %s)",
                    room.room_id,
                    meeting.meeting_id,
                    meeting.start.isoformat(),
                    meeting.end.isoformat(),
                )
            if subscription_manager is not None:
                await subscription_manager.on_meeting_change(meeting, room)

        watcher = CalendarWatcher(
            graph=graph,
            rooms=config.rooms,
            poll_interval_seconds=config.poll_interval_seconds,
            lookahead_minutes=config.meeting_lookahead_minutes,
            on_meeting_change=on_meeting_change,
            health=health,
        )

        publisher = HealthPublisher(ha=ha, health=health)

        tasks = [
            asyncio.create_task(relay.run(), name="relay-ws"),
            asyncio.create_task(publisher.run(), name="health-publisher"),
        ]
        if graph_credentials_ok:
            tasks.append(asyncio.create_task(watcher.run(), name="calendar-watcher"))
        else:
            log.warning("Graph credentials not configured; calendar watcher disabled")
        if subscription_manager is not None:
            tasks.append(
                asyncio.create_task(
                    subscription_manager.run_renewal_loop(), name="subscription-renewer"
                )
            )

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

        if subscription_manager is not None:
            log.info("Cleaning up %d subscription(s)", store.size())
            try:
                await asyncio.wait_for(subscription_manager.cleanup_all(), timeout=10)
            except asyncio.TimeoutError:
                log.warning("Subscription cleanup timed out")

        log.info("Shutdown complete")


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

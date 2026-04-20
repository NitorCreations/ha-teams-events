# Teams Events

Home Assistant add-on that triggers `room_modes.run_mode` from Microsoft Teams meeting events (for example, when a Teams room device joins a booked meeting).

The add-on polls each configured room mailbox's calendar on a short cycle, creates a Graph change-notification subscription on the nearest online meeting's `meetingCallEvents`, and calls the HA service when Graph pushes a matching event. Notifications are rich-content (resource data included) and are decrypted locally with a self-generated X.509 key pair.

## Configuration

| Option | Type | Description |
|--------|------|-------------|
| `tenant_id` | str | Entra (Azure AD) tenant id. |
| `client_id` | str | Entra app client id. The app must have `Calendars.Read` and `OnlineMeetings.Read.All` application permissions admin-consented. |
| `client_secret` | password | Entra app client secret. |
| `relay_ws_url` | url | `wss://...` of the relay deployed from `infra/cdk/`. |
| `relay_token` | password | Shared secret used to authenticate to the relay's WebSocket. |
| `graph_webhook_url` | url | `https://...` public URL that Graph posts notifications to (CDK stack output `WebhookUrl`). |
| `site_id` | str | Identifier sent in the relay `hello` frame. Defaults to `office-ha`. Pick distinct ids if running dev + prod instances against the same relay. |
| `ha_base_url` | str | Base URL for the HA REST API. Inside the add-on, leave as `http://supervisor/core`. |
| `poll_interval_seconds` | int | Calendar polling interval (default 30). |
| `meeting_lookahead_minutes` | int | How far ahead to watch for the next meeting (default 15). |
| `dedupe_window_seconds` | int | Window to suppress duplicate triggers per room (default 20). |
| `subscription_lifetime_minutes` | int | Lifetime requested for Graph subscriptions (default 55). Graph enforces a maximum for meeting-call-events subscriptions — see Graph docs. |
| `renewal_headroom_minutes` | int | Renew subscriptions this many minutes before expiry (default 15). |
| `subscription_state_path` | str | Where to persist subscription records (default `/data/subscriptions.json`). |
| `notification_cert_path` | str | Where to store the self-signed cert PEM (default `/data/notification_cert.pem`). |
| `notification_key_path` | str | Where to store the matching private key PEM (default `/data/notification_key.pem`). |
| `trigger_modes` | bool | If `true`, incoming events call `room_modes.run_mode`. Set `false` for a dry-run instance that does everything *except* the mode fire — useful for dev alongside an armed prod. |
| `log_level` | list | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |
| `rooms[]` | list | `room_id`, `account_email`, `mode_id` per room. `mode_id` is the `room_modes` id to activate on a Teams event for that room. |

## Room mapping

Each room entry maps a Microsoft Teams room mailbox to the `room_modes` mode that should run when a meeting is joined in that room:

```yaml
rooms:
  - room_id: "your_room"
    account_email: "room-your-room@example.com"
    mode_id: "your_room_jabra_teams"
```

## Subscription lifecycle

1. Calendar watcher polls each room mailbox for the next Teams meeting within the lookahead window.
2. When a new meeting is discovered (or replaces the prior one), the subscription manager double-URL-encodes its `joinWebUrl` and creates a Graph subscription on `communications/onlineMeetings(joinWebUrl='<encoded>')/meetingCallEvents` with `changeType=updated`, `includeResourceData=true`, and the add-on's base64-DER public cert.
3. A per-subscription `clientState` secret is generated and stored — the event router rejects notifications whose `clientState` does not match.
4. A renewal loop (every 60 s) PATCHes subscriptions whose expiry falls within `renewal_headroom_minutes`.
5. When the watched meeting changes or clears, the manager deletes the old subscription and creates a replacement (or nothing).
6. On clean shutdown, the manager best-effort DELETEs every subscription. Persisted state at `subscription_state_path` lets a restart pick up where it left off.

## Health sensors

On a 30 s cycle the add-on publishes the following entities via `POST /api/states`:

- `binary_sensor.teams_events_armed` — `on`/`off` mirroring the `trigger_modes` option. Useful to tell at a glance whether an instance is armed (prod) or dry-run (dev).
- `binary_sensor.teams_events_relay_connected` — relay WebSocket state.
- `sensor.teams_events_active_subscriptions` — number of subscriptions currently held.
- `sensor.teams_events_next_subscription_renewal` — timestamp of the earliest upcoming renewal.
- `sensor.teams_events_last_graph_auth` — timestamp of last successful Graph token acquisition.
- `sensor.teams_events_last_calendar_poll` — timestamp of last calendar poll.
- `sensor.teams_events_last_forwarded_event` — timestamp of last notification received from the relay.
- `sensor.teams_events_last_triggered_mode` — the `mode_id` that was last matched (populates even when `trigger_modes=false`, so a dry-run instance shows what *would* have fired).

See `docs/lovelace.dashboard_teams_events.json` for a ready-made admin dashboard layout.

## Status

End-to-end verified. Runs subscriptions on Graph `/beta` (the current tested endpoint for `meetingCallEvents` — `/v1.0` rejects the alternate-key resource form with 400 as of this writing). See `docs/operations.md` for the Entra + Teams-policy setup required before first run.

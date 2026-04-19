# Teams Events

Home Assistant add-on that triggers `room_modes.run_mode` from Microsoft Teams meeting events (for example, when a room device joins the meeting).

## Configuration

| Option | Type | Description |
|--------|------|-------------|
| `tenant_id` | str | Entra (Azure AD) tenant id. |
| `client_id` | str | Entra app client id. |
| `client_secret` | password | Entra app client secret. |
| `relay_ws_url` | url | `wss://...` of the public relay. |
| `relay_token` | password | Shared secret used to authenticate to the relay. |
| `graph_webhook_url` | url | `https://...` public URL that Graph posts notifications to (output `WebhookUrl` of the CDK stack). |
| `site_id` | str | Identifier sent in the relay `hello` frame. Defaults to `office-ha`. |
| `ha_base_url` | str | Base URL for the HA REST API. Inside the add-on, leave as `http://supervisor/core`. |
| `poll_interval_seconds` | int | Calendar polling interval (default 30). |
| `meeting_lookahead_minutes` | int | How far ahead to watch for the next meeting (default 15). |
| `dedupe_window_seconds` | int | Window to suppress duplicate triggers per room (default 20). |
| `subscription_lifetime_minutes` | int | Lifetime requested for Graph subscriptions (default 55). |
| `renewal_headroom_minutes` | int | Renew subscriptions this many minutes before expiry (default 15). |
| `subscription_state_path` | str | Where to persist subscription records (default `/data/subscriptions.json`). |
| `trigger_modes` | bool | If `true`, incoming events call `room_modes.run_mode`. Set `false` for log-only dry runs. |
| `log_level` | list | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |
| `rooms[]` | list | `room_id`, `account_email`, `mode_id` per room. |

## Room mapping

```yaml
rooms:
  - room_id: "kohonen"
    account_email: "room-kohonen@nitor.com"
    mode_id: "kohonen_jabra_teams"
  - room_id: "lovelace"
    account_email: "room-lovelace@nitor.com"
    mode_id: "lovelace_jabra_teams"
```

## Subscription lifecycle

1. Calendar watcher polls each room mailbox for the next Teams meeting within the lookahead window.
2. When a new meeting is discovered (or replaces the prior one), the subscription manager resolves the online-meeting id via `$filter=JoinWebUrl eq '...'` and creates a Graph subscription on `/communications/onlineMeetings/{id}` with `changeType=updated`.
3. A per-subscription `clientState` secret is generated and stored — the event router rejects notifications whose `clientState` does not match.
4. A renewal loop (every 60s) PATCHes subscriptions whose expiry falls within `renewal_headroom_minutes`.
5. When the watched meeting changes or clears, the manager deletes the old subscription and creates a replacement (or nothing).
6. On shutdown, the manager best-effort DELETEs every subscription. Persisted state at `subscription_state_path` lets a restart pick up where it left off.

## Status

Phase 3. Subscription manager, renewal loop, `clientState` validation, and `run_mode` triggering are wired. Health reporting as an HA sensor is still TODO (Phase 6).

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
| `site_id` | str | Identifier sent in the relay `hello` frame. Defaults to `office-ha`. |
| `ha_base_url` | str | Base URL for the HA REST API. Inside the add-on, leave as `http://supervisor/core`. |
| `poll_interval_seconds` | int | Calendar polling interval (default 30). |
| `meeting_lookahead_minutes` | int | How far ahead to watch for the next meeting (default 15). |
| `dedupe_window_seconds` | int | Window to suppress duplicate triggers per room (default 20). |
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

## Status

Phase 1 scaffold. Calendar polling and WebSocket delivery are wired; Graph subscription management and `run_mode` triggering are stubs (the router logs matches only).

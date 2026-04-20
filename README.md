# ha-teams-events

Home Assistant add-on + AWS relay that activates a Home Assistant room mode when a Microsoft Teams meeting event happens in a room. The canonical use case is a Teams room device (e.g. a Jabra terminal) pressing **Join** on a booked meeting: the add-on sees the meeting on the room's calendar, subscribes to its Graph change notifications, and when Teams reports `callStarted`, it fires `room_modes.run_mode` for the mapped room. The pipeline is device-agnostic — any `meetingCallEvents` notification for a watched meeting triggers the mode.

See `docs/architecture.md` for the design and `docs/operations.md` for the end-to-end setup.

## Components

- **`addon/teams_events/`** — Home Assistant add-on (Python 3.12). Polls room mailbox calendars via Microsoft Graph, creates/renews Graph subscriptions on the relevant meetings with a self-generated X.509 encryption cert, decrypts rich-content notifications locally, and calls `room_modes.run_mode` on match.
- **`relay/lambda/`** — AWS Lambda handlers (transport-only). Accepts Microsoft Graph webhook POSTs (validation + notification), and broadcasts raw payloads to every connected add-on over API Gateway WebSocket.
- **`infra/cdk/`** — AWS CDK app that deploys the relay (REST API + WebSocket API + four Lambdas + DynamoDB connections table + Secrets Manager-held shared secret).

## Features

- **Microsoft Graph subscriptions on `communications/onlineMeetings(joinWebUrl='…')/meetingCallEvents`** with `includeResourceData: true`. Requires a Teams `ApplicationAccessPolicy` grant (PowerShell) — see `docs/operations.md`.
- **Per-addon self-signed RSA-2048 X.509 encryption cert**, auto-generated on first run and persisted to `/data/notification_cert.pem`. Survives restarts — the same subscriptions keep decrypting after a restart.
- **Rich-content notification decryption** in-process: RSA-OAEP-SHA1 unwrap of the session key, HMAC-SHA256 verification, AES-256-CBC with IV=first-16-bytes-of-key, PKCS7 unpad. No external key services.
- **Per-subscription `clientState` validation** to reject forwarded payloads that don't match the record we created.
- **Persistent subscription state** at `/data/subscriptions.json` — survives restarts. On clean shutdown, all held subscriptions are DELETEd from Graph so the slot is free for another instance.
- **Dry-run mode** (`trigger_modes: false`) — the add-on still polls calendars, manages subscriptions, decrypts events, and publishes health sensors, but skips the actual `room_modes.run_mode` call. Useful for dev/staging instances that share an Entra app with production.
- **Home Assistant health sensors** pushed via the HA REST API on a 30 s cycle: `binary_sensor.teams_events_armed`, `binary_sensor.teams_events_relay_connected`, `sensor.teams_events_active_subscriptions`, `sensor.teams_events_next_subscription_renewal`, `sensor.teams_events_last_graph_auth`, `sensor.teams_events_last_calendar_poll`, `sensor.teams_events_last_forwarded_event`, `sensor.teams_events_last_triggered_mode`.
- **Ops dashboard layout** shipped in `docs/lovelace.dashboard_teams_events.json` — an admin-only view grouping the sensors above plus the downstream room-mode sensors.

## Status

End-to-end working against Microsoft Graph (`/beta/subscriptions`) with live `room_modes.run_mode` activation. Current add-on version: **0.2.5** — see GitHub releases for the full timeline.

**Known constraint:** Graph deduplicates subscriptions per `(resource, changeType, app)` tuple. A single Entra app can only hold one subscription on a given meeting. If you want to run two add-on instances in parallel (e.g. dev + prod), either register a second Entra app for the second instance, or run them single-owner (one armed, one stopped or in `trigger_modes: false` dry-run).

## Development

```bash
# Addon (local dev)
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m app.main   # reads /data/options.json or ./options.json

# CDK
cd infra/cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth
```

## Releasing the add-on image

Images are published to Docker Hub as `docker.io/nitor/ha-teams-events:{version}` — a single multi-arch manifest covering `linux/amd64` and `linux/arm64`. The add-on `config.yaml` points to that image and Docker resolves the correct arch at install time. Needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repo secrets (push rights to the `nitor/*` namespace).

The release workflow runs on GitHub release publish and requires the release tag to match the version in `addon/teams_events/config.yaml` (`v0.2.5` ↔ `version: "0.2.5"`).

To cut a release:

1. Bump `version:` in `addon/teams_events/config.yaml` and commit.
2. Push to `main`.
3. Create a GitHub release with tag `v<version>`. The workflow builds both architectures in one buildx run and pushes `:<version>` and `:latest` (for non-prereleases).

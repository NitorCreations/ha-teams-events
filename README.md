# ha-jabra-events

Automates room A/V mode activation when a Jabra room terminal joins a Microsoft Teams meeting.

See `docs/architecture.md` and the top-level design doc (`homeassistant-configuration/TEAMS_EVENTS.md`) for the full plan.

## Components

- **`addon/jabra_events/`** — Home Assistant add-on (Python). Polls room calendars via Microsoft Graph, manages Graph subscriptions for meeting call events, keeps a WebSocket open to the public relay, and triggers `room_modes.run_mode` when the Jabra terminal joins.
- **`relay/lambda/`** — AWS Lambda handlers (transport-only). Accepts Graph webhooks and forwards raw payloads to the connected add-on over WebSocket API Gateway.
- **`infra/cdk/`** — AWS CDK app deploying the relay (HTTP API, WebSocket API, Lambdas, DynamoDB connections table) into `eu-west-1`.

## Initial scope

Rooms: **Kohonen**, **Lovelace**.
Target modes: `kohonen_jabra_teams`, `lovelace_jabra_teams`.

## Status

Phase 1 scaffold. Graph auth and `run_mode` calls not yet wired; add-on runs but logs forwarded events without acting on them.

## Development

```bash
# Addon (local dev)
cd addon/jabra_events
python -m venv .venv && source .venv/bin/activate
pip install -e ./app
python -m app.main   # reads /data/options.json or ./options.json

# CDK
cd infra/cdk
pip install -r requirements.txt
cdk synth
AWS_PROFILE=nitor-infra cdk deploy
```

# ha-teams-events

Automates room A/V mode activation from Microsoft Teams meeting events for Home Assistant-managed rooms. The current trigger is a Teams room device (e.g. a Jabra room terminal) pressing **Join**, but the pipeline is device-agnostic.

See `docs/architecture.md` and the top-level design doc (`homeassistant-configuration/TEAMS_EVENTS.md`) for the full plan.

## Components

- **`addon/teams_events/`** — Home Assistant add-on (Python). Polls room calendars via Microsoft Graph, manages Graph subscriptions for meeting call events, keeps a WebSocket open to the public relay, and triggers `room_modes.run_mode` on the relevant event.
- **`relay/lambda/`** — AWS Lambda handlers (transport-only). Accepts Graph webhooks and forwards raw payloads to the connected add-on over WebSocket API Gateway.
- **`infra/cdk/`** — AWS CDK app deploying the relay (HTTP API, WebSocket API, Lambdas, DynamoDB connections table) into `eu-west-1`.

## Initial scope

Rooms: **Kohonen**, **Lovelace**.
Target modes: `kohonen_jabra_teams`, `lovelace_jabra_teams` (mode ids retain the `jabra_teams` suffix because that's how they're registered in `room_modes.yaml`).

## Status

Phase 1 scaffold. Graph auth and `run_mode` calls not yet wired; add-on runs but logs forwarded events without acting on them.

## Development

```bash
# Addon (local dev)
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -e ./app
python -m app.main   # reads /data/options.json or ./options.json

# CDK
cd infra/cdk
pip install -r requirements.txt
cdk synth
AWS_PROFILE=nitor-infra cdk deploy
```

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

Phase 3. Calendar watcher, subscription manager (create/renew/delete), relay WS client, and `room_modes.run_mode` triggering are wired. Observability sensors in HA are still TODO.

## Development

```bash
# Addon (local dev)
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m app.main   # reads /data/options.json or ./options.json

# CDK
cd infra/cdk
pip install -r requirements.txt
cdk synth
AWS_PROFILE=nitor-infra cdk deploy
```

## Releasing the add-on image

Images are published to Docker Hub as `docker.io/nitor/ha-teams-events:{version}` as a single multi-arch manifest (linux/amd64 + linux/arm64). The add-on `config.yaml` points to `docker.io/nitor/ha-teams-events` and Docker picks the correct arch on pull. Matches the `ha-nitor-backend` convention — needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repo secrets (the same ones `ha-nitor-backend` uses).

The release workflow runs when a GitHub release is **published** and requires the release tag to match the version in `addon/teams_events/config.yaml` (tag `v0.2.0` ↔ `version: "0.2.0"`).

To cut a release:

1. Bump `version:` in `addon/teams_events/config.yaml` and commit.
2. Push to `main`.
3. Create a GitHub release with tag `v<version>`. The workflow builds both architectures in one buildx run and pushes `:<version>` and `:latest` (for non-prereleases).

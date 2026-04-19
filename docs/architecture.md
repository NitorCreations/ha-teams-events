# Architecture

High-level flow (see `homeassistant-configuration/TEAMS_EVENTS.md` for the full design):

```
Jabra room terminal → Microsoft Graph → AWS relay (HTTP API) → WebSocket → HA add-on → room_modes.run_mode
```

Responsibilities:

- **Add-on (`addon/jabra_events/`)** — polls room calendars, creates/renews Graph subscriptions for meeting call events, keeps a persistent WebSocket to the relay, matches incoming notifications back to room/mode, and calls `room_modes.run_mode`.
- **Relay (`relay/lambda/`)** — transport-only. Accepts Graph webhooks and the Graph validation challenge, then fans out raw payloads to every connected add-on through the WebSocket management API. No room awareness.
- **Infra (`infra/cdk/`)** — deploys the relay: REST API + WebSocket API + four Lambda handlers + DynamoDB `Connections` table + shared-secret in Secrets Manager. Region: `eu-west-1`.

## Message shapes

Add-on → relay:

```json
{ "action": "hello", "site_id": "office-ha", "token": "<shared-secret>" }
{ "action": "ping",  "site_id": "office-ha" }
```

Relay → add-on:

```json
{
  "type": "graph_notification",
  "received_at": "2026-04-19T12:00:00Z",
  "payload": { "value": [ { "subscriptionId": "...", "changeType": "updated", "resource": "...", "clientState": "..." } ] }
}
```

## Status

Phase 1 (scaffold): add-on runs, opens WS, polls calendars. Graph subscription management and `room_modes.run_mode` calls are deferred to Phase 3/4.

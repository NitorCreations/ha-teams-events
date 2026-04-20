# Architecture

High-level flow:

```
Teams room device (e.g. Jabra) → Microsoft Graph → AWS relay (HTTP API)
  → WebSocket → HA add-on → room_modes.run_mode
```

## Components

- **Add-on (`addon/teams_events/`)** — long-running Python process inside a Home Assistant add-on container. Responsibilities:
  - Poll each configured room mailbox's `calendarView` for imminent Teams meetings.
  - For the next watched meeting in each room, create a Graph change-notification subscription on `communications/onlineMeetings(joinWebUrl='…')/meetingCallEvents` with `changeType=updated` and `includeResourceData=true`.
  - Maintain a single shared WebSocket connection to the relay.
  - Decrypt rich-content notifications received from the relay (RSA-OAEP-SHA1 + AES-256-CBC + HMAC-SHA256), validate `clientState` and subscription mapping, dedupe, and fire `room_modes.run_mode` with the configured `mode_id`.
  - Publish a snapshot of its internal health as HA entities every 30 s.

- **Relay (`relay/lambda/`)** — transport-only. No room awareness, no mode awareness, no subscription state. Responsibilities:
  - Accept Microsoft Graph validation challenges and webhook notification POSTs on an HTTP API Gateway endpoint.
  - Maintain a DynamoDB table of active WebSocket connections (keyed by `site_id` + `connection_id`).
  - Broadcast each received webhook payload to every connected add-on over the WebSocket management API.

- **Infra (`infra/cdk/`)** — AWS CDK app deploying the relay as a single CloudFormation stack `TeamsEventsRelay`:
  - API Gateway REST API with `GET`/`POST /graph/webhook`.
  - API Gateway WebSocket API with `$connect`/`$disconnect`/`$default` routes.
  - Four Lambda functions (Python 3.12) — one per handler, shared by module prefix.
  - DynamoDB `Connections` table (`RemovalPolicy.RETAIN`).
  - Secrets Manager shared-secret (also `RETAIN`) — used for `hello` authentication on the WebSocket.

## Relay message contract

Add-on → relay:

```json
{ "action": "hello", "site_id": "office-ha", "token": "<shared-secret>" }
{ "action": "ping",  "site_id": "office-ha" }
```

Relay → add-on:

```json
{
  "type": "graph_notification",
  "received_at": "2026-04-20T12:00:00Z",
  "payload": {
    "value": [
      {
        "subscriptionId": "…",
        "changeType": "updated",
        "resource": "communications/onlineMeetings(joinWebUrl='…')/meetingCallEvents",
        "clientState": "…",
        "encryptedContent": {
          "data": "<base64 AES-256-CBC ciphertext>",
          "dataKey": "<base64 RSA-OAEP-SHA1-wrapped AES key>",
          "dataSignature": "<base64 HMAC-SHA256 of data>",
          "encryptionCertificateId": "<thumbprint>",
          "encryptionCertificateThumbprint": "<sha1>"
        }
      }
    ]
  }
}
```

The add-on decrypts `encryptedContent` in-process — no external KMS, no Microsoft-side decryption service.

## Why a relay at all?

Microsoft Graph requires a public HTTPS endpoint to POST notifications to. Most Home Assistant instances are behind NAT / not directly reachable. The relay is the minimal amount of "public" infrastructure required to bridge Graph's push model to an outbound-only HA add-on over WebSocket. Keeping it transport-only (no per-room state, no mode knowledge) means the same relay can host any number of add-on instances (distinguished by `site_id`) without coordination.

## Single-owner model for subscriptions

Microsoft Graph deduplicates `/subscriptions` creation per `(resource, changeType, app)`. That means a single Entra application cannot hold two live subscriptions for the same meeting simultaneously, even from different processes or hosts. If you want two add-on instances to both have live subscriptions (e.g. dev + prod), either:

- register a second Entra app for the second instance (clean, independent subscription namespaces), or
- run a single-owner topology: only the "armed" instance actually holds subscriptions; the other runs with `trigger_modes: false` and will hit `409 Conflict` when its polls try to create, which is harmless noise.

The add-on's shutdown path (`cleanup_all`) DELETEs every held subscription so hand-off between instances is clean.

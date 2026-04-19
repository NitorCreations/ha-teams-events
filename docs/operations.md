# Operations

## Entra app registration (TODO)

Required scopes (application permissions):

- `Calendars.Read` — read room mailbox calendars.
- `OnlineMeetings.Read.All` — look up meeting metadata.
- (Subscription phase) a scope compatible with the `/communications/onlineMeetings` change-notification resource used for join events.

After creating the app:

1. Grant admin consent in the tenant.
2. Create a client secret; store it in the add-on options (`client_secret`).
3. Record `tenant_id` and `client_id` in the add-on options.

## Running the add-on locally

```bash
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -e ./app
cp options.example.json options.json   # (create this once we have a template)
python -m app.main
```

## Relay

Outputs from `cdk deploy TeamsEventsRelay`:

- `WebhookUrl` → use as Graph subscription `notificationUrl`.
- `WebSocketUrl` → set as add-on `relay_ws_url`.
- `SharedSecretArn` → fetch the value and set as add-on `relay_token`.

## Health

The add-on exposes health state internally via `Health.snapshot()`. Exposing it as an HA sensor is part of Phase 6.

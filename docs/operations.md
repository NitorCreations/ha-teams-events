# Operations

End-to-end setup playbook: Entra app → Teams policy → relay deploy → add-on install.

## 1. Register the Entra application

1. Entra admin center → **Applications → App registrations → New registration**.
2. Name: `ha-teams-events` (or anything). Account types: "Accounts in this organizational directory only".
3. No redirect URI. Register.
4. Record **Application (client) ID** and **Directory (tenant) ID** from the Overview blade.

## 2. Create a client secret

1. **Certificates & secrets → Client secrets → New client secret**.
2. Pick a long expiry (12–24 months); set a calendar reminder to rotate before it expires.
3. Copy the **secret value** immediately (only shown once).

## 3. Grant Graph API permissions

Under **API permissions → Add a permission → Microsoft Graph → Application permissions**, add:

| Permission | Purpose |
|---|---|
| `Calendars.Read` | Read `/users/{email}/calendarView` for each room mailbox — how we discover upcoming Teams meetings. |
| `OnlineMeetings.Read.All` | Required for subscribing to `meetingCallEvents` change notifications. |

Then **Grant admin consent for \<tenant\>**. Status should flip to "Granted for ...".

Fast path via `az`:

```bash
APP_ID=$(az ad app create \
  --display-name ha-teams-events \
  --sign-in-audience AzureADMyOrg \
  --required-resource-accesses '[{
    "resourceAppId": "00000003-0000-0000-c000-000000000000",
    "resourceAccess": [
      {"id": "798ee544-9d2d-430c-a058-570e29e34338", "type": "Role"},
      {"id": "c1684f21-1984-47fa-9d61-2dc8c296bb70", "type": "Role"}
    ]
  }]' \
  --query appId -o tsv)
az ad sp create --id "$APP_ID"
az ad app permission admin-consent --id "$APP_ID"
az ad app credential reset --id "$APP_ID" --display-name "ha-teams-events" --years 2
```

Prereqs: signed in to `az` as **Application Administrator** + **Privileged Role Administrator** (the admin-consent step requires the latter).

## 4. Teams Application Access Policy

Subscribing to a Teams meeting's change notifications is authorized against the **meeting organizer's** identity via a Teams **Application Access Policy**. Room mailboxes are typically invitees, not organizers, so a per-room grant is ineffective — you grant against organizers (or tenant-wide). For the common case where any staff member can book any room, tenant-wide is pragmatic:

```powershell
Connect-MicrosoftTeams

New-CsApplicationAccessPolicy `
  -Identity "ha-teams-events-policy" `
  -AppIds "<application-client-id>" `
  -Description "ha-teams-events add-on: access to Teams meeting call events"

Grant-CsApplicationAccessPolicy -PolicyName "ha-teams-events-policy" -Global
```

Propagation can take up to ~30 minutes.

**Headless admin session (Linux):** if you're already signed in to `az` with Teams Administrator activated, inject the existing tokens into PowerShell to skip the interactive browser flow:

```bash
TEAMS_TOKEN=$(az account get-access-token --resource 48ac35b8-9aa8-4d74-927d-1f4a14a0b239 --query accessToken -o tsv)
GRAPH_TOKEN=$(az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv)
export TEAMS_TOKEN GRAPH_TOKEN
pwsh -NoProfile -Command '
Connect-MicrosoftTeams -AccessTokens @($env:GRAPH_TOKEN, $env:TEAMS_TOKEN) | Out-Null
# ...run New- / Grant- cmdlets here...
Disconnect-MicrosoftTeams | Out-Null
'
```

## 5. Deploy the AWS relay

See `infra/cdk/README.md` for the CDK deploy. Capture the three stack outputs:

- `WebhookUrl` — the public HTTPS URL Graph will POST notifications to.
- `WebSocketUrl` — what the add-on connects to.
- `SharedSecretArn` — Secrets Manager ARN holding the shared-secret used by the add-on's `hello` frame.

## 6. Verify Graph access (before installing the add-on)

```bash
export TENANT_ID="..."
export CLIENT_ID="..."
export CLIENT_SECRET="..."
export ROOM="room-example@example.com"

TOKEN=$(curl -sS -X POST \
  "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&grant_type=client_credentials&scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
END=$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)
curl -sS -G "https://graph.microsoft.com/v1.0/users/${ROOM}/calendarView" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "startDateTime=$START" \
  --data-urlencode "endDateTime=$END" \
  --data-urlencode '$select=id,subject,start,end,isOnlineMeeting,onlineMeeting' \
  | python3 -m json.tool | head -40
```

`{"value": [...]}` (even empty) means Steps 3 and admin-consent are working.

The add-on looks up meetings via the organizer context, not the room. A 404 on an OData `$filter=JoinWebUrl eq '…'` lookup against `/users/<room>/onlineMeetings` is **not** a failure signal — rooms are invitees, not organizers, so that filter always returns 404 for room mailboxes. What matters is the `POST /beta/subscriptions` call the add-on makes (you'll see it succeed in the add-on log once installed).

## 7. Install the add-on

On each Home Assistant instance:

```bash
ha store add https://github.com/NitorCreations/ha-teams-events
ha store reload
ha apps install <slug>        # slug is <repo-hash>_teams_events; see ha store apps --raw-json
```

Push the full options blob via the Supervisor API (on the HA host, where `SUPERVISOR_TOKEN` is exported):

```bash
cat > /tmp/teams-opts.json <<EOF
{"options": {
  "tenant_id": "<tenant>",
  "client_id": "<client>",
  "client_secret": "<secret>",
  "relay_ws_url": "<WebSocketUrl>",
  "relay_token": "<value from SharedSecretArn>",
  "graph_webhook_url": "<WebhookUrl>",
  "site_id": "home-assistant",
  "ha_base_url": "http://supervisor/core",
  "poll_interval_seconds": 30,
  "meeting_lookahead_minutes": 15,
  "dedupe_window_seconds": 20,
  "subscription_lifetime_minutes": 55,
  "renewal_headroom_minutes": 15,
  "subscription_state_path": "/data/subscriptions.json",
  "notification_cert_path": "/data/notification_cert.pem",
  "notification_key_path": "/data/notification_key.pem",
  "trigger_modes": true,
  "log_level": "INFO",
  "rooms": [
    {"room_id": "example", "account_email": "room-example@example.com", "mode_id": "example_jabra_teams"}
  ]
}}
EOF
curl -sS -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  http://supervisor/addons/<slug>/options --data @/tmp/teams-opts.json
ha apps start <slug>
```

Expect the log to show `Acquired Graph token`, `Relay hello sent`, a calendar poll per room, and `Created subscription <id>` once a meeting falls into the lookahead window.

## 8. Dual-instance (dev + prod) operation

Because a single Entra app can hold only one subscription per `(resource, changeType)`, running two add-on instances against the same app means one owns the subscription and the other hits `409 Conflict` every poll.

Two clean options:

- **Single-owner (zero extra setup):** keep one instance armed (`trigger_modes: true`) and the other running with `trigger_modes: false` (or stopped). The dry-run instance still polls calendars, keeps its WS open, decrypts notifications (which it ignores because its subscription_store is empty), and publishes `binary_sensor.teams_events_armed = off`. Before testing a new add-on release on dev, `ha apps stop` the prod instance first — its `cleanup_all` releases all Graph subscriptions — then start dev. Reverse to go back.
- **Two Entra apps:** register a second app (`ha-teams-events-dev` etc.) with the same permissions + admin consent + `Grant-CsApplicationAccessPolicy`, give the dev instance its own credentials. Independent subscription namespaces, no conflict, both armed.

## Health + dashboard

The add-on publishes a snapshot of its state to HA every 30 s as state-pushed entities. See `addon/teams_events/DOCS.md` for the full list. A ready-made admin dashboard definition is at `docs/lovelace.dashboard_teams_events.json` — drop it into `.storage/lovelace.dashboard_teams_events` and add a matching entry to `.storage/lovelace_dashboards`, or paste the view config into the HA Lovelace editor.

## Running the add-on locally (development)

```bash
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m app.main   # reads /data/options.json or ./options.json
```

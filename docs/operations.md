# Operations

## Entra app registration

### 1. Register the application

1. Entra admin center → **Applications → App registrations → New registration**.
2. Name: `ha-teams-events` (or similar). Account types: "Accounts in this organizational directory only".
3. No redirect URI. Register.
4. Record **Application (client) ID** and **Directory (tenant) ID** from the Overview blade.

### 2. Create a client secret

1. **Certificates & secrets → Client secrets → New client secret**.
2. Pick a long expiry (12–24 months); set a calendar reminder to rotate before it expires.
3. Copy the **secret value** immediately (only shown once).

### 3. Grant API permissions

Under **API permissions → Add a permission → Microsoft Graph → Application permissions**, add:

| Permission | Purpose |
|---|---|
| `Calendars.Read` | Read `/users/{email}/calendarView` for each room mailbox — how we discover upcoming Teams meetings. |
| `OnlineMeetings.Read.All` | Read `/users/{email}/onlineMeetings` so we can resolve a meeting id from its `joinWebUrl`. Also required for subscribing to online-meeting change notifications. |

Then **Grant admin consent for \<tenant\>**. The status should flip to "Granted for ...".

### 4. Allow the app to access online meetings (Teams policy)

Calling `/users/{email}/onlineMeetings` and subscribing to meeting-change notifications requires the tenant to authorize the app against specific user mailboxes via a Teams **Application Access Policy**. A Teams admin runs this once in PowerShell (MicrosoftTeams module):

```powershell
Connect-MicrosoftTeams

# 1. Create the policy (once).
New-CsApplicationAccessPolicy `
  -Identity "ha-teams-events-policy" `
  -AppIds "<application-client-id>" `
  -Description "ha-teams-events add-on: access to room mailbox online meetings"

# 2. Grant the policy to the specific room accounts.
Grant-CsApplicationAccessPolicy `
  -PolicyName "ha-teams-events-policy" `
  -Identity "room-kohonen@nitor.com"

Grant-CsApplicationAccessPolicy `
  -PolicyName "ha-teams-events-policy" `
  -Identity "room-lovelace@nitor.com"
```

Grants can take ~30 minutes to propagate. To verify:

```powershell
Get-CsUserPolicyAssignment -Identity "room-kohonen@nitor.com" -PolicyType ApplicationAccessPolicy
```

### 5. Verification (token + calendar read)

Before putting values into the add-on, sanity-check with curl. Export the three values:

```bash
export TENANT_ID="..."
export CLIENT_ID="..."
export CLIENT_SECRET="..."
```

Acquire a token:

```bash
TOKEN=$(curl -sS -X POST \
  "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&grant_type=client_credentials&scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
echo "token length: ${#TOKEN}"
```

Read the next hour of meetings on a room calendar:

```bash
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
END=$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)
curl -sS -G "https://graph.microsoft.com/v1.0/users/room-kohonen@nitor.com/calendarView" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "startDateTime=$START" \
  --data-urlencode "endDateTime=$END" \
  --data-urlencode '$select=id,subject,start,end,isOnlineMeeting,onlineMeeting' \
  | python3 -m json.tool | head -40
```

If this returns `{"value": [...]}` (even empty), Step 3 + admin consent are working.

For the online-meetings endpoint (Step 4 dependency):

```bash
curl -sS "https://graph.microsoft.com/v1.0/users/room-kohonen@nitor.com/onlineMeetings?\$filter=JoinWebUrl%20eq%20'https://teams.microsoft.com/l/meetup-join/...'" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expect HTTP 200 + possibly empty `value`. A `403` here means the Application Access Policy in Step 4 hasn't been granted (or hasn't propagated yet).

### 6. Plug values into the add-on

Once calendar + online-meetings calls succeed, set the three options on the dev add-on:

```bash
ssh root@office-assistant.dev.nitor.zone 'curl -sS -X POST \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  http://supervisor/addons/c81b1d35_teams_events/options \
  -d "$(cat)" ' <<EOF
{"options":{
  "tenant_id":"<tenant>",
  "client_id":"<client>",
  "client_secret":"<secret>",
  "relay_ws_url":"wss://zr91fdjjpl.execute-api.eu-west-1.amazonaws.com/prod",
  "relay_token":"<shared-secret>",
  "graph_webhook_url":"https://m1msmwpvtc.execute-api.eu-west-1.amazonaws.com/prod/graph/webhook",
  "site_id":"office-ha",
  "ha_base_url":"http://supervisor/core",
  "poll_interval_seconds":30,
  "meeting_lookahead_minutes":15,
  "dedupe_window_seconds":20,
  "subscription_lifetime_minutes":55,
  "renewal_headroom_minutes":15,
  "subscription_state_path":"/data/subscriptions.json",
  "trigger_modes":true,
  "log_level":"INFO",
  "rooms":[
    {"room_id":"kohonen","account_email":"room-kohonen@nitor.com","mode_id":"kohonen_jabra_teams"},
    {"room_id":"lovelace","account_email":"room-lovelace@nitor.com","mode_id":"lovelace_jabra_teams"}
  ]
}}
EOF

ssh root@office-assistant.dev.nitor.zone 'ha apps restart c81b1d35_teams_events'
```

Then watch the logs — you should see `Acquired Graph token` and calendar poll entries.

## Running the add-on locally

```bash
cd addon/teams_events
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m app.main   # reads /data/options.json or ./options.json
```

## Relay

Outputs from `cdk deploy TeamsEventsRelay`:

- `WebhookUrl` → register with Microsoft Graph as the subscription `notificationUrl`; also the add-on's `graph_webhook_url`.
- `WebSocketUrl` → add-on's `relay_ws_url`.
- `SharedSecretArn` → fetch the value with `aws secretsmanager get-secret-value` and put it in `relay_token`.

Current live values are recorded in `infra/cdk/README.md`.

## Health

The add-on exposes health state internally via `Health.snapshot()`. Exposing it as an HA sensor is part of Phase 6.

# Teams events relay — AWS CDK

Deploys:

- API Gateway REST API for `POST /graph/webhook` (Microsoft Graph notifications and validation challenges).
- API Gateway WebSocket API (`$connect`, `$disconnect`, `$default`) for the HA add-on.
- Four Lambdas (`webhook_handler`, `websocket_connect`, `websocket_disconnect`, `websocket_default`).
- DynamoDB table `Connections` (keyed by `site_id` + `connection_id`).
- Secrets Manager secret holding the shared relay token.

## Prerequisites

- AWS profile: `nep nitor-infra` (or equivalent credentials).
- Region: `eu-west-1`.
- Python 3.12+, Node 18+ (for the CDK CLI).

```bash
cd infra/cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Bootstrap (once per account/region)

```bash
AWS_PROFILE=nitor-infra CDK_DEFAULT_REGION=eu-west-1 \
  npx cdk bootstrap aws://<account-id>/eu-west-1
```

## Deploy

```bash
AWS_PROFILE=nitor-infra CDK_DEFAULT_REGION=eu-west-1 \
  npx cdk deploy TeamsEventsRelay
```

Outputs:

- `WebhookUrl` — register this with Microsoft Graph as the subscription `notificationUrl`.
- `WebSocketUrl` — set as `relay_ws_url` in the add-on config.
- `SharedSecretArn` — read the secret value and put it in the add-on `relay_token` option.

## Notes

- The Lambda code under `relay/lambda/` is bundled directly (no build step).
  The CDK stack reads it via `Code.from_asset`, so deploys pick up local edits.
- The shared secret is injected into Lambda env at synth time
  (`Secret.secret_value.unsafe_unwrap()`). Rotate via CFN re-deploy.

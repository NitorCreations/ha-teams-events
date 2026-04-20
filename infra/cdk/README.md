# Teams events relay — AWS CDK

Deploys:

- API Gateway REST API for `POST /graph/webhook` (Microsoft Graph notifications and validation challenges).
- API Gateway WebSocket API (`$connect`, `$disconnect`, `$default`) for the HA add-on.
- Four Lambdas (`webhook_handler`, `websocket_connect`, `websocket_disconnect`, `websocket_default`).
- DynamoDB table `Connections` (keyed by `site_id` + `connection_id`).
- Secrets Manager secret holding the shared relay token.

Deploys are **run locally**. The relay changes very rarely so a GitHub Actions pipeline is not worth the OIDC setup.

## Prerequisites

- AWS credentials for your chosen account with permission to create the resources above (simplest: AdministratorAccess on the account during initial bootstrap, scoped down afterwards).
- A region you want the relay deployed in — the stack honours `CDK_DEFAULT_REGION` (default `eu-west-1`).
- Python 3.12+ (the `aws-cdk-lib` wheels ship up to 3.13).
- Node 18+ for the `cdk` CLI — either `npx cdk` or a global `npm install -g aws-cdk@2`.

```bash
cd infra/cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Bootstrap (once per account/region)

```bash
# Assume/export AWS credentials however you normally do (AWS_PROFILE, AWS SSO,
# aws-vault, nameless-deploy-tools, etc.)
CDK_DEFAULT_REGION=eu-west-1 npx cdk bootstrap aws://<account-id>/eu-west-1
```

## Diff / deploy

```bash
CDK_DEFAULT_REGION=eu-west-1 npx cdk diff TeamsEventsRelay
CDK_DEFAULT_REGION=eu-west-1 npx cdk deploy TeamsEventsRelay --outputs-file cdk-outputs.json
```

Outputs (also written to `cdk-outputs.json`):

- `WebhookUrl` — register with Microsoft Graph as the subscription `notificationUrl`; also set as the add-on's `graph_webhook_url` option.
- `WebSocketUrl` — set as the add-on's `relay_ws_url`.
- `SharedSecretArn` — fetch the secret value and set as the add-on's `relay_token`:
  ```bash
  aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text
  ```
- `ConnectionsTableName` — for ops/debug visibility into who's connected.

## Tearing down

```bash
CDK_DEFAULT_REGION=eu-west-1 npx cdk destroy TeamsEventsRelay
```

The DynamoDB table and Secrets Manager secret are created with `RETAIN`, so they survive a stack destroy. Delete them manually if you want them gone.

## Notes

- The Lambda code under `relay/lambda/` is bundled directly (no build step). The CDK stack reads it via `Code.from_asset`, so deploys pick up local edits.
- The shared secret is resolved into each Lambda's environment at synth time via `Secret.secret_value.unsafe_unwrap()`. Rotating the secret requires re-deploying the stack.
- The relay is completely transport-only. Running multiple HA add-on instances against one relay is fine — each instance identifies itself with a distinct `site_id` in its `hello` frame, and the DynamoDB `Connections` table can hold them all.

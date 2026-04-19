from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigw,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_secretsmanager as secrets,
)
from aws_cdk.aws_apigatewayv2_alpha import (
    WebSocketApi,
    WebSocketRouteOptions,
    WebSocketStage,
)
from aws_cdk.aws_apigatewayv2_integrations_alpha import (
    WebSocketLambdaIntegration,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[3]
LAMBDA_ROOT = REPO_ROOT / "relay" / "lambda"


class RelayStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        connections = ddb.Table(
            self,
            "Connections",
            partition_key=ddb.Attribute(name="site_id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="connection_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        shared_secret = secrets.Secret(
            self,
            "RelaySharedSecret",
            description="Shared secret between the Teams events relay and the HA add-on",
            generate_secret_string=secrets.SecretStringGenerator(
                password_length=48, exclude_punctuation=True
            ),
        )

        code = _lambda.Code.from_asset(str(LAMBDA_ROOT))

        def lambda_fn(name: str, handler_module: str) -> _lambda.Function:
            fn = _lambda.Function(
                self,
                name,
                runtime=_lambda.Runtime.PYTHON_3_12,
                handler=f"{handler_module}.handler",
                code=code,
                timeout=Duration.seconds(10),
                memory_size=256,
                log_retention=logs.RetentionDays.ONE_MONTH,
                environment={
                    "CONNECTIONS_TABLE": connections.table_name,
                },
            )
            connections.grant_read_write_data(fn)
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[shared_secret.secret_arn],
                )
            )
            # Mirror the secret value into an env var at cold-start via CFN
            # resolution — OK for a single shared secret.
            fn.add_environment(
                "RELAY_SHARED_SECRET",
                shared_secret.secret_value.unsafe_unwrap(),
            )
            return fn

        webhook = lambda_fn("WebhookHandler", "webhook_handler")
        ws_connect = lambda_fn("WsConnect", "websocket_connect")
        ws_disconnect = lambda_fn("WsDisconnect", "websocket_disconnect")
        ws_default = lambda_fn("WsDefault", "websocket_default")

        ws_api = WebSocketApi(
            self,
            "WsApi",
            connect_route_options=WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration("WsConnectInt", ws_connect),
            ),
            disconnect_route_options=WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration("WsDisconnectInt", ws_disconnect),
            ),
            default_route_options=WebSocketRouteOptions(
                integration=WebSocketLambdaIntegration("WsDefaultInt", ws_default),
            ),
        )

        ws_stage = WebSocketStage(
            self,
            "WsStage",
            web_socket_api=ws_api,
            stage_name="prod",
            auto_deploy=True,
        )

        # Allow the lambdas that post back to connected clients to use the
        # management API for this specific stage.
        ws_api.grant_manage_connections(webhook)
        ws_api.grant_manage_connections(ws_default)

        ws_endpoint = f"https://{ws_api.api_id}.execute-api.{self.region}.amazonaws.com/{ws_stage.stage_name}"
        for fn in (webhook, ws_default):
            fn.add_environment("WS_MANAGEMENT_ENDPOINT", ws_endpoint)

        http_api = apigw.RestApi(
            self,
            "WebhookApi",
            rest_api_name="teams-events-webhook",
            deploy_options=apigw.StageOptions(stage_name="prod"),
        )
        graph = http_api.root.add_resource("graph")
        webhook_resource = graph.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(webhook, proxy=True),
        )
        webhook_resource.add_method(
            "GET",  # Graph sends validation as a POST with query string, but
            # some tooling probes with GET; harmless to accept.
            apigw.LambdaIntegration(webhook, proxy=True),
        )

        cdk.CfnOutput(self, "WebhookUrl", value=f"{http_api.url}graph/webhook")
        cdk.CfnOutput(
            self,
            "WebSocketUrl",
            value=f"wss://{ws_api.api_id}.execute-api.{self.region}.amazonaws.com/{ws_stage.stage_name}",
        )
        cdk.CfnOutput(self, "SharedSecretArn", value=shared_secret.secret_arn)
        cdk.CfnOutput(self, "ConnectionsTableName", value=connections.table_name)

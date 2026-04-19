from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .connections import all_connections, delete_connection

log = logging.getLogger(__name__)

WS_ENDPOINT = os.environ.get("WS_MANAGEMENT_ENDPOINT", "")


def _client():
    if not WS_ENDPOINT:
        raise RuntimeError("WS_MANAGEMENT_ENDPOINT is not configured")
    return boto3.client("apigatewaymanagementapi", endpoint_url=WS_ENDPOINT)


def forward_to_all(payload: dict[str, Any]) -> int:
    """Broadcast a graph_notification message to every connected add-on.

    Returns the number of successful deliveries.
    """
    message = {
        "type": "graph_notification",
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }
    body = json.dumps(message).encode("utf-8")
    client = _client()
    delivered = 0
    for item in all_connections():
        try:
            client.post_to_connection(ConnectionId=item["connection_id"], Data=body)
            delivered += 1
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "GoneException":
                log.info("Pruning stale connection %s", item["connection_id"])
                delete_connection(item["site_id"], item["connection_id"])
            else:
                log.exception("Failed to forward to %s: %s", item["connection_id"], exc)
    return delivered


def send_to(connection_id: str, message: dict[str, Any]) -> None:
    client = _client()
    client.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps(message).encode("utf-8"),
    )

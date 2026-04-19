from __future__ import annotations

import os
import time
from typing import Iterable

import boto3

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "teams-relay-connections")

_ddb = boto3.resource("dynamodb")
_table = _ddb.Table(CONNECTIONS_TABLE)


def put_connection(site_id: str, connection_id: str) -> None:
    now = int(time.time())
    _table.put_item(
        Item={
            "site_id": site_id,
            "connection_id": connection_id,
            "connected_at": now,
            "last_seen_at": now,
        }
    )


def touch_connection(site_id: str, connection_id: str) -> None:
    _table.update_item(
        Key={"site_id": site_id, "connection_id": connection_id},
        UpdateExpression="SET last_seen_at = :ts",
        ExpressionAttributeValues={":ts": int(time.time())},
    )


def delete_connection(site_id: str, connection_id: str) -> None:
    _table.delete_item(Key={"site_id": site_id, "connection_id": connection_id})


def delete_connection_everywhere(connection_id: str) -> None:
    """Best-effort removal when we don't know the site_id (disconnect event)."""
    scan = _table.scan(
        FilterExpression="connection_id = :c",
        ExpressionAttributeValues={":c": connection_id},
        ProjectionExpression="site_id, connection_id",
    )
    for item in scan.get("Items", []):
        _table.delete_item(
            Key={"site_id": item["site_id"], "connection_id": item["connection_id"]}
        )


def all_connections() -> Iterable[dict]:
    response = _table.scan(ProjectionExpression="site_id, connection_id")
    yield from response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = _table.scan(
            ProjectionExpression="site_id, connection_id",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        yield from response.get("Items", [])

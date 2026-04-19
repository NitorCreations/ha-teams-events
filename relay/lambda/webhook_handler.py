from __future__ import annotations

import json
import logging
from typing import Any

from shared.forwarder import forward_to_all

log = logging.getLogger()
log.setLevel(logging.INFO)


def _text_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain"},
        "body": body,
    }


def _json_response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    query = event.get("queryStringParameters") or {}
    validation_token = query.get("validationToken")
    if validation_token is not None:
        log.info("Responding to Graph validation request")
        return _text_response(200, validation_token)

    body_raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        body_raw = base64.b64decode(body_raw).decode("utf-8")
    try:
        payload = json.loads(body_raw)
    except json.JSONDecodeError:
        log.warning("Invalid JSON body: %r", body_raw[:500])
        return _text_response(400, "invalid json")

    notifications = payload.get("value") or []
    log.info("Received Graph notification batch: %d item(s)", len(notifications))
    delivered = forward_to_all(payload)
    log.info("Forwarded to %d connection(s)", delivered)
    return _json_response(202, {"forwarded": delivered})

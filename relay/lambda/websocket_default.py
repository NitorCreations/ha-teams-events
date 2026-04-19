from __future__ import annotations

import json
import logging
from typing import Any

from shared.auth import verify_token
from shared.connections import put_connection, touch_connection
from shared.forwarder import send_to

log = logging.getLogger()
log.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId")
    body_raw = event.get("body") or "{}"
    try:
        message = json.loads(body_raw)
    except json.JSONDecodeError:
        log.warning("Invalid message from %s: %r", connection_id, body_raw[:200])
        return {"statusCode": 400}

    action = message.get("action")
    if action == "hello":
        site_id = message.get("site_id") or ""
        token = message.get("token") or ""
        if not site_id or not verify_token(token):
            log.warning("Rejecting hello from %s (site_id=%r)", connection_id, site_id)
            return {"statusCode": 401}
        put_connection(site_id, connection_id)
        log.info("Registered connection %s as site=%s", connection_id, site_id)
        try:
            send_to(connection_id, {"type": "hello_ack", "site_id": site_id})
        except Exception as exc:  # pragma: no cover - best-effort ack
            log.warning("hello_ack failed: %s", exc)
        return {"statusCode": 200}

    if action == "ping":
        # We don't have site_id on a raw ping; tables are keyed by (site_id,
        # connection_id), so we only touch if the client includes site_id.
        site_id = message.get("site_id")
        if site_id:
            touch_connection(site_id, connection_id)
        return {"statusCode": 200}

    log.info("Unknown action %r from %s", action, connection_id)
    return {"statusCode": 400}

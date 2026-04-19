from __future__ import annotations

import logging
from typing import Any

from shared.auth import verify_token

log = logging.getLogger()
log.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    # Optional per-connection auth via ?token=...; the add-on also sends a
    # `hello` frame with site_id + token which is validated in websocket_default.
    query = event.get("queryStringParameters") or {}
    token = query.get("token")
    if token and not verify_token(token):
        log.warning("Rejecting connect: bad token")
        return {"statusCode": 401}
    log.info("WebSocket connect: %s", event.get("requestContext", {}).get("connectionId"))
    return {"statusCode": 200}

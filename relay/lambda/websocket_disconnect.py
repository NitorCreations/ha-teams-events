from __future__ import annotations

import logging
from typing import Any

from shared.connections import delete_connection_everywhere

log = logging.getLogger()
log.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId")
    log.info("WebSocket disconnect: %s", connection_id)
    if connection_id:
        delete_connection_everywhere(connection_id)
    return {"statusCode": 200}

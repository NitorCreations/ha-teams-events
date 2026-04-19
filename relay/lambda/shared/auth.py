from __future__ import annotations

import hmac
import os

RELAY_SHARED_SECRET_ENV = "RELAY_SHARED_SECRET"


def expected_secret() -> str:
    return os.environ.get(RELAY_SHARED_SECRET_ENV, "")


def verify_token(provided: str) -> bool:
    expected = expected_secret()
    if not expected:
        return False
    return hmac.compare_digest(expected, provided or "")

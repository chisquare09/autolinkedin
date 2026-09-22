from __future__ import annotations

import hmac
from typing import Any


def authorize(
    headers: dict[str, str],
    *,
    mode: str,
    bearer_token: str = "",
    query_secret: str = "",
    expected_secret: str = "",
) -> None:
    if mode == "bearer":
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, bearer_token):
            raise PermissionError("invalid bearer token")
        return
    if mode == "query_secret":
        if not hmac.compare_digest(query_secret, expected_secret):
            raise PermissionError("invalid webhook secret")
        return
    raise PermissionError(f"unsupported webhook authentication mode: {mode}")

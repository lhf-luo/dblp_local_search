"""Opaque cursor carrying only the query fingerprint and last row position."""

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any

#做hash值，为了分页处理
def fingerprint(value: Mapping[str, Any]) -> str:
    value = {key: item for key, item in value.items() if key != "cursor"}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

#over review
def encode(last: int, query: str) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps({"last": last, "q": query}).encode())
        .decode()
        .rstrip("=")
    )

#over review
def decode(token: str | None, query: str) -> int:
    if token is None:
        return 0
    try:
        data: Any = json.loads(
            base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
        )
        if (
            data["q"] != query
            or type(data["last"]) is not int
            or not 0 <= data["last"] <= 2**63 - 1
        ):
            raise ValueError("Cursor belongs to another query")
        return data["last"]
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError(
            "Invalid cursor or changed query; restart without cursor"
        ) from error

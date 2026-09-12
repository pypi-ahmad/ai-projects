"""Pull a raw tenant key out of request headers.

Framework-agnostic on purpose: tests pass a plain `dict[str, str]`; the
real app (src/api/app.py, via src/auth/resolve.py) passes Starlette's
case-insensitive `Headers`. Both work via `.get`, which is why both
header-name casings are tried below -- belt-and-braces for a plain dict,
redundant-but-harmless for the real case-insensitive mapping.
"""

from __future__ import annotations

from collections.abc import Mapping


def extract_raw_key(headers: Mapping[str, str]) -> str | None:
    """`Authorization: Bearer <key>` takes precedence over `X-Api-Key`."""
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value

    api_key = headers.get("X-Api-Key") or headers.get("x-api-key")
    return api_key or None

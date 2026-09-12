"""Admin auth: a single shared token in `X-Admin-Token`, never a tenant key.

Deliberately a separate header and a separate function from tenant-key
resolution (`src/auth/resolve.py`) -- a valid tenant key must never satisfy
admin auth, so there is no shared code path that could blur the two.

Called from src/api/deps.py::require_admin, which every route in
src/api/admin_routes.py depends on.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping

from src.auth.errors import InvalidAdminTokenError

ADMIN_TOKEN_ENV = "ADMIN_TOKEN"


def verify_admin(headers: Mapping[str, str], admin_token: str | None = None) -> None:
    """Raises InvalidAdminTokenError unless X-Admin-Token matches the
    configured admin token. `admin_token` defaults to `$ADMIN_TOKEN`; tests
    pass it explicitly instead of depending on process environment."""
    expected = admin_token if admin_token is not None else os.environ.get(ADMIN_TOKEN_ENV)
    provided = headers.get("X-Admin-Token") or headers.get("x-admin-token")

    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise InvalidAdminTokenError()

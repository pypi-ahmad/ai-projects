"""Optional X-Admin-Token gate for write endpoints.

Enforced only if OBS_ADMIN_TOKEN is set in the environment; open otherwise.
This app binds 127.0.0.1 only - the token is defense in depth, not the
primary boundary.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException


def require_admin_token(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("OBS_ADMIN_TOKEN")
    if not expected:
        return  # no token configured -> open
    if x_admin_token != expected:
        raise HTTPException(status_code=401, detail="missing or invalid X-Admin-Token")

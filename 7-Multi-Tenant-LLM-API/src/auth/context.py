"""What a handler is allowed to know about who's calling.

src/api/deps.py::get_context attaches one of these per request. Handlers
must read tenant_id/key_id from here, never from the request body (see
docs/TENANCY.md) -- body.tenant_id is never trusted input.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    key_id: str

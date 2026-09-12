"""FastAPI dependency-injection functions used by src/api/app.py and
src/api/admin_routes.py -- this module must not contain route logic or
business logic itself, only wiring: a DB session per request, the
resolved tenant/admin identity, and the provider dispatcher. Routes take
these via `Depends(...)`; test files override `get_session` and
`get_dispatcher` in `app.dependency_overrides` instead of hitting a real
DB or a real upstream provider (see tests/conftest.py). Open
src/api/app.py to see them used.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.auth.admin import verify_admin
from src.auth.context import RequestContext
from src.auth.resolve import authenticate
from src.db import SessionLocal
from src.providers.registry import Dispatcher, dispatch


def get_session() -> Generator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_context(request: Request, session: Session = Depends(get_session)) -> RequestContext:
    return authenticate(session, request.headers)


def get_dispatcher() -> Dispatcher:
    """A plain function, injected via Depends() so tests can override it
    with a fake instead of calling a real upstream provider."""
    return dispatch


def require_admin(request: Request) -> None:
    """X-Admin-Token only -- a valid tenant key never satisfies this (see
    src/auth/admin.py). Raises InvalidAdminTokenError, caught by the
    AuthError handler in src/api/app.py."""
    verify_admin(request.headers)

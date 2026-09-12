"""Auth/authz failures with a stable `code` (safe to return to the caller)
and an `http_status`. Caught by the `AuthError` exception handler in
src/api/app.py, which turns both into `{"error": exc.code}`."""

from __future__ import annotations


class AuthError(Exception):
    code: str
    http_status: int

    def __init__(self) -> None:
        super().__init__(self.code)


class MissingCredentialsError(AuthError):
    """No Authorization/X-Api-Key header present."""

    code = "missing_credentials"
    http_status = 401


class InvalidKeyError(AuthError):
    """No active key's hash matches -- covers both an unknown prefix and a
    wrong secret for a known prefix. Same code either way: an attacker who
    doesn't hold a valid secret can't distinguish "no such key" from "wrong
    secret for a real key" (see docs/THREAT_NOTES.md)."""

    code = "invalid_key"
    http_status = 401


class KeyRevokedError(AuthError):
    """The exact secret matched a key, but that key has been revoked. Only
    reachable by someone who already holds the real secret, so revealing
    this (vs. a generic invalid_key) doesn't help an attacker enumerate
    anything -- see docs/THREAT_NOTES.md."""

    code = "key_revoked"
    http_status = 401


class TenantSuspendedError(AuthError):
    """Key is valid; the owning tenant's status is suspended. 403, not 401
    -- the caller is who they say they are, just not currently allowed."""

    code = "tenant_suspended"
    http_status = 403


class InvalidAdminTokenError(AuthError):
    code = "invalid_admin_token"
    http_status = 401

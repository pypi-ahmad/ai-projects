"""Allowlisted API metadata; response text never enters diagnostics.

Every field on `PageDiagnostic`/`FilterAnnotation` is either a bounded
literal, a count, or a value that passed `safe_identifier`'s allowlist --
never raw provider text, headers, or request/response bodies. Must not: gain
a free-text field (e.g. a raw error message) without also redacting it --
that would defeat the point of this module, since `PageDiagnostic` is shown
directly in the UI (see src/ui/app.py's "API diagnostics" expander) and may
be persisted in ParseResult JSON.

Next: src/extract.py's `_invoke_structured`, where these fields are
populated from a real (or mocked) API response.
"""

import os
import re
from typing import Literal

from pydantic import BaseModel, Field


class FilterAnnotation(BaseModel):
    source: Literal["prompt", "completion"]
    category: Literal["hate", "sexual", "violence", "self_harm", "jailbreak"]
    filtered: bool | None = None
    severity: Literal["safe", "low", "medium", "high"] | None = None


class PageDiagnostic(BaseModel):
    page: int | None = None
    outcome: Literal["parsed", "content_filtered", "refused", "incomplete", "invalid_response", "http_error", "transport_error"] = "invalid_response"
    http_status: int | None = None
    request_id: str | None = None
    model: str | None = None
    requested_model: str | None = None
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls", "function_call"] | None = None
    usage_known: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cache_write_tokens: int | None = None
    filters: list[FilterAnnotation] = Field(default_factory=list)


class ExtractionCallError(Exception):
    def __init__(self, diagnostic: PageDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(f"Extraction request failed: {diagnostic.outcome}")


def safe_identifier(value) -> str | None:
    # Three independent layers, any of which can veto the value: (1) shape --
    # short, plain-token-looking strings only, which already excludes most
    # free-form provider text; (2) known secret-ish substrings/URLs, in case
    # something token-shaped still looks like a credential; (3) a literal
    # match against any currently-configured secret-like env var value, so an
    # actual configured key never echoes back even if it doesn't match (2).
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value):
        return None
    if re.search(r"(?i)(sk-|bearer|api.key|token=)", value) or "://" in value:
        return None
    if any(secret and len(secret) >= 8 and secret in value for name, secret in os.environ.items()
           if any(part in name.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))):
        return None
    return value


def token_count(value) -> int | None:
    # `type(value) is int` (not isinstance) deliberately excludes bool: bool
    # is an int subclass in Python, and a stray True/False from a malformed
    # response body must not be reported as a token count of 1/0.
    return value if type(value) is int and value >= 0 else None


def filter_annotations(data, source: Literal["prompt", "completion"]) -> list[FilterAnnotation]:
    if not isinstance(data, dict):
        return []
    results = []
    for category in ("hate", "sexual", "violence", "self_harm", "jailbreak"):
        item = data.get(category)
        if not isinstance(item, dict):
            continue
        filtered = item.get("filtered") if type(item.get("filtered")) is bool else None
        severity = item.get("severity") if item.get("severity") in ("safe", "low", "medium", "high") else None
        if filtered is not None or severity is not None:
            results.append(FilterAnnotation(source=source, category=category, filtered=filtered, severity=severity))
    return results

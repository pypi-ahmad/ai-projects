"""Quota check failures, raised by src/quota/limiter.py::check_quota.
RateLimitError subclasses carry retry_after (seconds) and map to 429, per
docs/LIMITS.md. The other two are permission denials, not rate/budget
issues, so they don't carry a retry_after. Caught by the `QuotaError`
exception handler in src/api/app.py, which adds a `Retry-After` header
only for the RateLimitError subclasses."""

from __future__ import annotations


class QuotaError(Exception):
    code: str
    http_status: int

    def __init__(self) -> None:
        super().__init__(self.code)


class ModelNotAllowedError(QuotaError):
    code = "MODEL_NOT_ALLOWED"
    http_status = 403


class ProviderNotAllowedError(QuotaError):
    code = "PROVIDER_NOT_ALLOWED"
    http_status = 403


class MaxTokensPerRequestExceededError(QuotaError):
    code = "MAX_TOKENS_PER_REQUEST"
    http_status = 400


class RateLimitError(QuotaError):
    http_status = 429

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__()


class RpmExceededError(RateLimitError):
    code = "RATE_RPM"


class RpdExceededError(RateLimitError):
    code = "RATE_RPD"


class BudgetMonthExceededError(RateLimitError):
    code = "BUDGET_MONTH"

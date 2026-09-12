"""Generic retry wrapper: providers pass their own is_retryable(exc) predicate
so each SDK's exception types stay local to that provider module.
"""

import time
from collections.abc import Callable

DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5


def call_with_retries[T](
    func: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool],
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    # `retries=2` means up to 3 total calls to `func` (the initial attempt plus 2
    # retries). Backoff grows linearly with attempt number (0.5s, 1.0s, ...), not
    # exponentially. Every provider's `is_retryable` predicate only matches
    # server-side errors (5xx) -- a 4xx means the request itself is invalid and
    # retrying it would just fail again the same way.
    attempt = 0
    while True:
        try:
            return func()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            attempt += 1
            sleep(backoff_seconds * attempt)

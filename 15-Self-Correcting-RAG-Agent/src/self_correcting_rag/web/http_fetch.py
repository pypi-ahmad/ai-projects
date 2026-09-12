"""HttpWebFetch: a safe HTTP(S) GET fetcher. Scheme allowlist and private-IP
block (web/safety.py), timeout, byte cap, and a one-off request with no
cookie jar -- so no cookies from the user's machine or prior responses are
ever sent.
"""

import urllib.error
import urllib.request

from self_correcting_rag.web.safety import assert_safe_url

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 1_000_000
DEFAULT_MAX_CHARS = 20_000


class WebFetchError(Exception):
    """Raised when a fetch is blocked or fails."""


class HttpWebFetch:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_chars = max_chars

    def fetch(self, url: str) -> str:
        assert_safe_url(url)
        request = urllib.request.Request(
            url, headers={"User-Agent": "self-correcting-rag-agent/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = response.read(self._max_bytes)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise WebFetchError(f"fetch failed for {url!r}: {e}") from e

        return raw.decode("utf-8", errors="replace")[: self._max_chars]

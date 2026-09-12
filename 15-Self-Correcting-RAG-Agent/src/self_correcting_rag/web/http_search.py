"""HttpSearch: a real WebSearch backed by Firecrawl's documented POST
/v2/search endpoint (Bearer auth, JSON body {"query", "limit"}, response
`data.web[]` with url/title/markdown) -- verified against Firecrawl's docs,
not guessed. Configure with SEARCH_API_KEY (a Firecrawl API key) and
SEARCH_BASE_URL (default https://api.firecrawl.dev).
"""

import json
import urllib.error
import urllib.request

from self_correcting_rag.web.base import WebResult

DEFAULT_BASE_URL = "https://api.firecrawl.dev"
DEFAULT_TIMEOUT = 10.0


class HttpSearchError(Exception):
    """Raised when the search request fails."""


class HttpSearch:
    def __init__(
        self, *, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(self, query: str, n: int) -> list[WebResult]:
        body = json.dumps({"query": query, "limit": n}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/v2/search",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise HttpSearchError(f"search failed for {query!r}: {e}") from e

        results = payload.get("data", {}).get("web", [])
        return [
            WebResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                # The documented example response doesn't show a dedicated
                # snippet field -- fall back to a truncated markdown excerpt.
                snippet=item.get("description") or (item.get("markdown") or "")[:300],
            )
            for item in results
            if item.get("url")
        ]

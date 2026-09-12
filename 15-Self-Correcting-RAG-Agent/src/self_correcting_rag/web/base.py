"""WebSearch and WebFetch: two separate plug-in interfaces for the optional
web fallback step. Fetched pages are untrusted (see docs/THREAT_NOTES.md) --
implementations return plain text only; callers must never execute or follow
anything inside it.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str


class WebSearch(Protocol):
    def search(self, query: str, n: int) -> list[WebResult]:
        """Returns up to n candidate results for `query`."""


class WebFetch(Protocol):
    def fetch(self, url: str) -> str:
        """Returns `url`'s page text as plain text, truncated to a size cap.
        Raises on a blocked or failed fetch -- never returns partial trust.
        """

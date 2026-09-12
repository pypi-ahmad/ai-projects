"""NullSearch: always returns no results. The safe default when no search
backend is configured (see config.Settings.resolve_web_enabled).
"""

from self_correcting_rag.web.base import WebResult


class NullSearch:
    def search(self, query: str, n: int) -> list[WebResult]:
        return []

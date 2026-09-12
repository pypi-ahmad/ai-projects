"""FileStubSearch: reads canned search results from a JSON fixture, for tests
-- no network calls. Expected shape:
{"<query>": [{"title": "...", "url": "...", "snippet": "..."}, ...], ...}
"""

import json
from pathlib import Path

from self_correcting_rag.web.base import WebResult


class FileStubSearch:
    def __init__(self, fixture_path: Path) -> None:
        data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        self._results_by_query = {
            query: [WebResult(**item) for item in items] for query, items in data.items()
        }

    def search(self, query: str, n: int) -> list[WebResult]:
        return self._results_by_query.get(query, [])[:n]

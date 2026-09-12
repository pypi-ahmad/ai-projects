"""HttpSearch's Firecrawl /v2/search request construction and response
parsing, verified without a live call (urllib.request.urlopen mocked).
"""

import json
import urllib.request

from self_correcting_rag.web.http_search import HttpSearch


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_search_builds_documented_request_and_parses_response(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["body"] = json.loads(request.data)
        return _FakeResponse(
            {
                "success": True,
                "data": {
                    "web": [
                        {"url": "https://example.test/a", "title": "A", "markdown": "some content"}
                    ]
                },
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    search = HttpSearch(api_key="fake-key", base_url="https://api.firecrawl.dev")
    results = search.search("test query", 5)

    assert captured["url"] == "https://api.firecrawl.dev/v2/search"
    assert captured["method"] == "POST"
    assert captured["headers"]["authorization"] == "Bearer fake-key"
    assert captured["body"] == {"query": "test query", "limit": 5}

    assert len(results) == 1
    assert results[0].url == "https://example.test/a"
    assert results[0].title == "A"
    assert results[0].snippet == "some content"

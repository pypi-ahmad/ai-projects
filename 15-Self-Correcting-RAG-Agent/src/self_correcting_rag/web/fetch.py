"""Fetches top-N web page texts for a set of queries: search via WebSearch,
fetch via WebFetch, deduped by URL. A single bad search or fetch does not
fail the whole run.
"""

import logging

from self_correcting_rag.web.base import WebFetch, WebResult, WebSearch
from self_correcting_rag.web.records import WebChunk

logger = logging.getLogger(__name__)

DEFAULT_N = 3


def fetch_web_chunks(
    web_search: WebSearch, web_fetch: WebFetch, queries: list[str], *, n: int = DEFAULT_N
) -> list[WebChunk]:
    seen_urls: set[str] = set()
    hits: list[WebResult] = []
    for query in queries:
        try:
            results = web_search.search(query, n)
        except Exception:
            logger.warning("web search failed for query %r, skipping", query, exc_info=True)
            continue
        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                hits.append(result)

    chunks = []
    for hit in hits[:n]:
        try:
            text = web_fetch.fetch(hit.url)
        except Exception:
            logger.warning("web fetch failed for %s, skipping", hit.url, exc_info=True)
            continue
        if text.strip():
            chunks.append(WebChunk(url=hit.url, title=hit.title, text=text))
    return chunks

"""Optional web fallback: WebSearch/WebFetch interfaces (base.py), a safety gate for
fetched URLs (safety.py, http_fetch.py), and concrete search backends (null_search.py,
file_stub_search.py, http_search.py). Fetched content is untrusted -- see
docs/THREAT_NOTES.md -- and must never be treated as instructions by any caller. Start
reading at web/base.py.
"""

"""Minimal stand-in for a ChatOpenAI client, used by tests that exercise
src.extract's `_invoke_structured` (directly or via extract_invoice/
extract_regions/crop_and_extract/parse_page) without a real network call.
Mimics only the attributes `_invoke_structured` actually reads
(`root_client.chat.completions.with_raw_response.create`, `model_name`,
`reasoning_effort`) -- not the rest of ChatOpenAI's surface.

Must not: grow real HTTP/network behavior; keep this a pure in-memory fake
whose response is fixed at construction time.

Next: src/extract.py's `_invoke_structured`, the function this fakes.
"""

import json
from types import SimpleNamespace


class FakeLLM:
    def __init__(self, result):
        self.reasoning_effort = "medium"
        self.model_name = "gpt-6-sol"
        data = result.model_dump() if result is not None else None
        raw = SimpleNamespace(status_code=200, headers={"x-request-id": "req-test"},
                              parse=lambda: SimpleNamespace(model_dump=lambda: {
                                  "model": "test-model", "choices": [{"finish_reason": "stop",
                                  "message": {"content": json.dumps(data)}}],
                              }))
        self.root_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            with_raw_response=SimpleNamespace(create=lambda **kwargs: raw))))

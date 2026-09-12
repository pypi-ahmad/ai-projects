"""Thin client for Ollama's embeddings HTTP API.

Uses stdlib urllib, not the `ollama` package or `requests` -- one JSON POST
doesn't earn a dependency, and it keeps the boundary trivial to mock in
tests (mocked HTTP returning a fixed vector).

Endpoint and JSON shape verified against Ollama's own docs
(https://github.com/ollama/ollama/blob/main/docs/api.md, "Generate
Embeddings"), not guessed:

    POST /api/embed
    request:  {"model": str, "input": str | list[str], "dimensions"?: int}
    response: {"model": str, "embeddings": list[list[float]], ...}

`input` as a single string still returns a 2-D `embeddings` list (one
vector). `/api/embeddings` (singular) is the older endpoint `/api/embed`
has superseded -- not used here.
"""

import json
import urllib.error
import urllib.request

DEFAULT_EMBED_MODEL = "qwen3-embedding:0.6b"
REBUILD_EMBED_MODEL = "qwen3-embedding:4b"

_OLLAMA_HOST = "http://localhost:11434"
_EMBED_PATH = "/api/embed"


class OllamaEmbedError(RuntimeError):
    """Raised when Ollama's /api/embed call fails or Ollama is unreachable."""


def resolve_embed_model(high_quality: bool = False) -> str:
    """The default embed model, or the rebuild-quality one behind a flag."""
    return REBUILD_EMBED_MODEL if high_quality else DEFAULT_EMBED_MODEL


def _post_embed(
    *,
    model: str,
    input_: str | list[str],
    dimensions: int | None,
    host: str,
) -> dict:
    payload: dict = {"model": model, "input": input_}
    if dimensions is not None:
        payload["dimensions"] = dimensions

    request = urllib.request.Request(
        host + _EMBED_PATH,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaEmbedError(f"Ollama /api/embed returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaEmbedError(f"Ollama /api/embed unreachable at {host}: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaEmbedError(f"Ollama /api/embed returned non-JSON body: {body!r}") from exc


def embed_one(
    text: str,
    *,
    model: str = DEFAULT_EMBED_MODEL,
    dimensions: int | None = None,
    host: str = _OLLAMA_HOST,
) -> list[float]:
    """Embed a single query, for lookup."""
    data = _post_embed(model=model, input_=text, dimensions=dimensions, host=host)
    return data["embeddings"][0]


def embed_batch(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    dimensions: int | None = None,
    host: str = _OLLAMA_HOST,
) -> list[list[float]]:
    """Embed many queries at once, for backfill."""
    data = _post_embed(model=model, input_=texts, dimensions=dimensions, host=host)
    return data["embeddings"]

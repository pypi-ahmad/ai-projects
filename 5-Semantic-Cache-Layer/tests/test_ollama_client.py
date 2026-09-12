import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src.embed.ollama_client import (
    DEFAULT_EMBED_MODEL,
    REBUILD_EMBED_MODEL,
    OllamaEmbedError,
    embed_batch,
    embed_one,
    resolve_embed_model,
)

FIXED_VECTOR = [0.1, 0.2, 0.3, 0.4]


def _fake_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_embed_one_returns_fixed_vector(mock_urlopen):
    mock_urlopen.return_value = _fake_response(
        {"model": DEFAULT_EMBED_MODEL, "embeddings": [FIXED_VECTOR]}
    )

    result = embed_one("hello", model=DEFAULT_EMBED_MODEL)

    assert result == FIXED_VECTOR
    sent = json.loads(mock_urlopen.call_args[0][0].data)
    assert sent == {"model": DEFAULT_EMBED_MODEL, "input": "hello"}


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_embed_batch_returns_one_vector_per_input(mock_urlopen):
    vectors = [FIXED_VECTOR, [v + 1 for v in FIXED_VECTOR]]
    mock_urlopen.return_value = _fake_response(
        {"model": DEFAULT_EMBED_MODEL, "embeddings": vectors}
    )

    result = embed_batch(["a", "b"], model=DEFAULT_EMBED_MODEL)

    assert result == vectors
    sent = json.loads(mock_urlopen.call_args[0][0].data)
    assert sent == {"model": DEFAULT_EMBED_MODEL, "input": ["a", "b"]}


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_dimensions_param_forwarded_when_set(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"embeddings": [FIXED_VECTOR[:2]]})

    embed_one("hello", dimensions=2)

    sent = json.loads(mock_urlopen.call_args[0][0].data)
    assert sent["dimensions"] == 2


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_dimensions_param_omitted_by_default(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"embeddings": [FIXED_VECTOR]})

    embed_one("hello")

    sent = json.loads(mock_urlopen.call_args[0][0].data)
    assert "dimensions" not in sent


def test_resolve_embed_model_flag():
    assert resolve_embed_model() == DEFAULT_EMBED_MODEL
    assert resolve_embed_model(high_quality=False) == DEFAULT_EMBED_MODEL
    assert resolve_embed_model(high_quality=True) == REBUILD_EMBED_MODEL


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_http_error_raises_typed_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="http://localhost:11434/api/embed",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(b'{"error": "model not found"}'),
    )

    with pytest.raises(OllamaEmbedError):
        embed_one("hello")


@patch("src.embed.ollama_client.urllib.request.urlopen")
def test_connection_failure_raises_typed_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    with pytest.raises(OllamaEmbedError):
        embed_one("hello")

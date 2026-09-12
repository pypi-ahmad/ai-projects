"""OpenAI-compatible chat completions (shared HTTP layer for Agnes + OpenAI providers).

_post() is intentionally reused by providers/agnes.py (imported by leading-
underscore name) since Agnes exposes the same request/response shape; keep
both call sites in mind before changing this function's signature or errors.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Callable, Tuple

from .base import MissingKeyError, ProviderError, ProviderResult
from ..gateway.models import GatewayRequest

ApproxFn = Callable[[str, str], Tuple[int, int]]


def _post(
    request: GatewayRequest,
    model: str,
    timeout_s: int,
    approx_fn: ApproxFn,
    base_url: str,
    api_key: str,
) -> ProviderResult:
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.append({"role": "user", "content": request.user_text})

    body: dict = {"model": model, "messages": messages}
    if request.need_json:
        body["response_format"] = {"type": "json_object"}
    if request.max_tokens:
        body["max_tokens"] = request.max_tokens

    url = f"{base_url.rstrip('/')}/chat/completions"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    # Retry once, only on a 5xx — see ollama.py for the same pattern. A 4xx
    # (bad request, auth failure) is not retried since a retry would fail
    # identically; it is remapped to ProviderError immediately instead.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = json.loads(resp.read())
            # KeyError/IndexError here means the endpoint responded 200 with a
            # body that doesn't match the OpenAI chat/completions shape —
            # caught separately below and remapped, not silently swallowed.
            text = raw["choices"][0]["message"]["content"]
            usage = raw.get("usage", {})
            in_t = usage.get("prompt_tokens") or 0
            out_t = usage.get("completion_tokens") or 0
            approx = False
            if not (in_t or out_t):
                in_t, out_t = approx_fn(request.user_text, text)
                approx = True
            return ProviderResult(text=text, in_tokens=in_t, out_tokens=out_t, approximate=approx)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code >= 500 and attempt == 0:
                continue
            raise ProviderError(f"HTTP {exc.code}") from exc
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response shape: {exc}") from exc
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
    raise ProviderError(str(last_exc))


def complete(
    request: GatewayRequest,
    model: str,
    timeout_s: int,
    approx_fn: ApproxFn,
) -> ProviderResult:
    """OpenAI-compatible provider: reads OPENAI_API_KEY + OPENAI_BASE_URL."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if not api_key or not base_url:
        raise MissingKeyError("OPENAI_API_KEY or OPENAI_BASE_URL not set")
    return _post(request, model, timeout_s, approx_fn, base_url, api_key)

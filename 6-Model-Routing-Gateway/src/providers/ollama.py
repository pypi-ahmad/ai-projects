"""Ollama /api/chat adapter — no API key required."""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Callable, Tuple

from .base import ProviderError, ProviderResult
from ..gateway.models import GatewayRequest

ApproxFn = Callable[[str, str], Tuple[int, int]]


def complete(
    request: GatewayRequest,
    model: str,
    timeout_s: int,
    approx_fn: ApproxFn,
) -> ProviderResult:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.append({"role": "user", "content": request.user_text})

    body: dict = {"model": model, "messages": messages, "stream": False}
    if request.need_json:
        body["format"] = "json"

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Retry once, only on a 5xx response — a transient overload on the local
    # Ollama server is worth one retry; anything else (4xx, connection error,
    # bad JSON) is not, and is remapped to ProviderError below so the caller's
    # fallback loop (route/executor.py) can move to the next target.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = json.loads(resp.read())
            text = raw.get("message", {}).get("content", "")
            # Ollama reports counts in prompt_eval_count/eval_count when it has
            # them; fall back to a tiktoken estimate (approx=True) otherwise.
            in_t = raw.get("prompt_eval_count") or 0
            out_t = raw.get("eval_count") or 0
            approx = False
            if not (in_t or out_t):
                in_t, out_t = approx_fn(request.user_text, text)
                approx = True
            return ProviderResult(text=text, in_tokens=in_t, out_tokens=out_t, approximate=approx)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code >= 500 and attempt == 0:
                continue  # retry once on 5xx
            raise ProviderError(f"HTTP {exc.code}") from exc
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
    raise ProviderError(str(last_exc))

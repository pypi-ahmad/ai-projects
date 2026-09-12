"""Google Gemini REST adapter — uses GOOGLE_API_KEY.

The API key is passed as a `key=` query parameter (Gemini's REST auth scheme,
not a header) — the constructed `url` below therefore contains the secret in
plain text. Do not log, print, or include `url`/`req.full_url` in any error
message or usage record.
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
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def complete(
    request: GatewayRequest,
    model: str,
    timeout_s: int,
    approx_fn: ApproxFn,
) -> ProviderResult:
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise MissingKeyError("GOOGLE_API_KEY not set")

    url = f"{_BASE}/{model}:generateContent?key={api_key}"

    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": request.user_text}]}]
    }
    if request.system:
        body["systemInstruction"] = {"parts": [{"text": request.system}]}

    gen_cfg: dict = {}
    if request.need_json:
        gen_cfg["responseMimeType"] = "application/json"
    if request.max_tokens:
        gen_cfg["maxOutputTokens"] = request.max_tokens
    if gen_cfg:
        body["generationConfig"] = gen_cfg

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Retry once, only on a 5xx — see ollama.py for the same pattern.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = json.loads(resp.read())
            # Assumes exactly one candidate with a single text part — Gemini
            # can return zero candidates (e.g. blocked by safety filters) or
            # multiple; that shape is not handled here and would raise
            # KeyError/IndexError, caught and remapped below.
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            um = raw.get("usageMetadata", {})
            in_t = um.get("promptTokenCount") or 0
            out_t = um.get("candidatesTokenCount") or 0
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

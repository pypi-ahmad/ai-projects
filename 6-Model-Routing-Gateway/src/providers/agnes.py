"""Agnes AI provider — OpenAI-compatible endpoint at apihub.agnes-ai.com."""
from __future__ import annotations
import os
from typing import Callable, Tuple

from .base import MissingKeyError, ProviderResult
# Agnes AI exposes an OpenAI-compatible chat/completions endpoint, so this
# adapter reuses openai_compat.py's request/response handling rather than
# duplicating it. The leading underscore marks _post as internal to this
# package, not a public provider API — only agnes.py and openai_compat.py
# itself should import it.
from .openai_compat import _post
from ..gateway.models import GatewayRequest

ApproxFn = Callable[[str, str], Tuple[int, int]]
_BASE_URL = "https://apihub.agnes-ai.com/v1"


def complete(
    request: GatewayRequest,
    model: str,
    timeout_s: int,
    approx_fn: ApproxFn,
) -> ProviderResult:
    api_key = os.environ.get("AGNES_API_KEY", "")
    if not api_key:
        raise MissingKeyError("AGNES_API_KEY not set")
    return _post(request, model, timeout_s, approx_fn, _BASE_URL, api_key)

"""Check whether a provider target is available at routing decision time.

All checks are fast (env var lookup or short HTTP probe).
Never raises — returns False on any error.
"""
from __future__ import annotations
import json
import os
import urllib.request


def _ollama_installed(host: str) -> set[str]:
    """Return the set of installed Ollama model names; empty set if unreachable."""
    # Not cached: route/router.py calls default_available() once per
    # candidate Ollama target, so a tier with several Ollama targets issues
    # that many separate /api/tags requests per routing decision. The 2 s
    # timeout keeps any single call cheap, but it is not batched.
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as resp:
            data = json.loads(resp.read())
            return {m["name"] for m in data.get("models", [])}
    except Exception:
        return set()


def default_available(provider: str, model: str) -> bool:
    """Return True if this provider/model target can be called right now.

    Ollama: model must be in the installed list (calls /api/tags with 2 s timeout).
    Cloud providers: corresponding API key env var must be non-empty.
    """
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return model in _ollama_installed(host)
    if provider == "agnes":
        return bool(os.environ.get("AGNES_API_KEY"))
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"))
    if provider == "gemini":
        return bool(os.environ.get("GOOGLE_API_KEY"))
    return False

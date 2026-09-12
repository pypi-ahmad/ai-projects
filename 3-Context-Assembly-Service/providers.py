"""
Compression provider chain. Packing always works offline; providers are optional.

Priority order: Ollama → Agnes AI → OpenAI-compat → Gemini.
All calls are best-effort: a provider that fails or is unconfigured is skipped silently
(the broad except/timeout in every _*_compress helper below is deliberate, not an
oversight — a network error here must degrade to COMPRESS_UNAVAILABLE, never raise).
Provider output is substituted into the packed context as-is, with no post-validation:
the prompt in _compress_prompt() asks the provider to preserve "[D1]"-style source
tags, but nothing here enforces that it actually did.
"""
from __future__ import annotations
import os, json
import urllib.request
from typing import Optional

_OLLAMA_COMPRESS_MODELS = ["qwen3.5:2b", "qwen3.5:0.8b"]       # full path preference
_OLLAMA_COMPRESS_TINY   = ["qwen3.5:0.8b", "qwen3.5:2b"]       # tiny path preference


def _ollama_host() -> str:
    return os.getenv("OLLAMA_HOST", "http://localhost:11434")


def ollama_available_models() -> list[str]:
    """Return names of installed Ollama models; empty list if Ollama unreachable."""
    try:
        with urllib.request.urlopen(f"{_ollama_host()}/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def _best_compress_model(installed: list[str], tiny: bool = False) -> Optional[str]:
    preference = _OLLAMA_COMPRESS_TINY if tiny else _OLLAMA_COMPRESS_MODELS
    for model in preference:
        if model in installed:
            return model
    return None


def _compress_prompt(text: str, target_tokens: int, must_keep: str = "") -> str:
    base = (
        f"Shorten the following to under {target_tokens} tokens. "
        "Preserve all entities, numbers, and source tags (e.g. [D1], [T1]). "
        "Do not add new facts. Reply with the shortened text only."
    )
    if must_keep:
        base += f" You must keep: {must_keep}."
    return f"{base}\n\n{text}"


def _ollama_compress(text: str, target_tokens: int, model: str,
                     must_keep: str = "") -> Optional[str]:
    try:
        payload = json.dumps({
            "model": model,
            "prompt": _compress_prompt(text, target_tokens, must_keep),
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{_ollama_host()}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["response"].strip()
    except Exception:
        return None


def _openai_compat_compress(
    text: str, target_tokens: int, base_url: str, api_key: str, model: str,
    must_keep: str = "",
) -> Optional[str]:
    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user",
                          "content": _compress_prompt(text, target_tokens, must_keep)}],
        }).encode()
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions", data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _gemini_compress(text: str, target_tokens: int, model: str, api_key: str,
                     must_keep: str = "") -> Optional[str]:
    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": _compress_prompt(text, target_tokens, must_keep)}]}],
        }).encode()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:generateContent?key={api_key}"
        )
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


def compress(text: str, target_tokens: int, tiny: bool = False,
             must_keep: str = "") -> Optional[str]:
    """
    Compress text using the first available provider.
    tiny=True uses the smaller Ollama model (qwen3.5:0.8b preferred).
    Returns compressed text or None if all providers unavailable or fail.
    """
    # 1. Ollama
    installed = ollama_available_models()
    model = _best_compress_model(installed, tiny=tiny)
    if model:
        result = _ollama_compress(text, target_tokens, model, must_keep)
        if result:
            return result

    # 2. Agnes AI (OpenAI-compatible)
    agnes_key = os.getenv("AGNES_API_KEY")
    if agnes_key:
        result = _openai_compat_compress(
            text, target_tokens,
            "https://apihub.agnes-ai.com/v1", agnes_key, "agnes-2.5-flash", must_keep,
        )
        if result:
            return result

    # 3. OpenAI-compatible (custom base URL)
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_base = os.getenv("OPENAI_BASE_URL")
    if openai_key and openai_base:
        result = _openai_compat_compress(
            text, target_tokens, openai_base, openai_key, "gpt-5.6-luna", must_keep,
        )
        if result:
            return result

    # 4. Gemini
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        result = _gemini_compress(text, target_tokens, "gemini-3.5-flash-lite", google_key, must_keep)
        if result:
            return result

    return None


def ollama_unload(model: str) -> None:
    """Best-effort: ask Ollama to unload a model immediately (keep_alive=0)."""
    try:
        payload = json.dumps({
            "model": model, "prompt": "", "keep_alive": 0, "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{_ollama_host()}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

"""Optional generate-on-miss demo providers (NOTES.md: generation is not
this repo's core job -- this exists only to demo what a caller might do
after a Miss, wired into the Streamlit UI's "generate and store" button).

Each provider is one stdlib urllib POST -- no SDK dependency for a demo
path. Request/response shapes verified against each provider's own docs,
not guessed:
  Ollama:            POST /api/generate {model, prompt, stream:false} -> response.response
  OpenAI-compatible: POST {base_url}/chat/completions {model, messages} -> choices[0].message.content
  Gemini:            POST .../v1beta/models/{model}:generateContent -> candidates[0].content.parts[0].text

Agnes AI is OpenAI-compatible (same request/response shape as the generic
"openai_compatible" provider, different base URL/key/model) -- per Agnes
AI's own documented contract (base URL, key, and model fixed below).
"""

import json
import os
import urllib.error
import urllib.request

OLLAMA_HOST = "http://localhost:11434"
GEMINI_HOST = "https://generativelanguage.googleapis.com"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"

# provider key -> models offered in the UI dropdown. Not granite4.1:3b --
# hardware discipline (README.md 4060 note) keeps it out of this demo path.
PROVIDERS: dict[str, list[str]] = {
    "ollama": ["qwen3.5:0.8b", "qwen3.5:2b"],
    "agnes": ["agnes-2.5-flash"],
    "openai_compatible": ["gpt-5.6-luna", "gpt-5.6-terra"],
    "gemini": ["gemini-3.5-flash-lite", "gemini-3.7-flash"],
}


class GenerateError(RuntimeError):
    """A demo provider call failed: missing key, unreachable host, bad response."""


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GenerateError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GenerateError(f"{url} unreachable: {exc.reason}") from exc


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise GenerateError(f"required environment variable {name} is not set")
    return value


def _generate_ollama(model: str, prompt: str) -> str:
    data = _post_json(
        f"{OLLAMA_HOST}/api/generate",
        {"model": model, "prompt": prompt, "stream": False},
        {"Content-Type": "application/json"},
    )
    return data["response"]


def _generate_openai_compatible(base_url: str, api_key: str, model: str, prompt: str) -> str:
    data = _post_json(
        f"{base_url.rstrip('/')}/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}]},
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    return data["choices"][0]["message"]["content"]


def _generate_gemini(api_key: str, model: str, prompt: str) -> str:
    data = _post_json(
        f"{GEMINI_HOST}/v1beta/models/{model}:generateContent",
        {"contents": [{"parts": [{"text": prompt}]}]},
        {"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


def generate(provider: str, model: str, prompt: str) -> str:
    """Call the chosen demo provider. Raises GenerateError on any failure
    -- callers (the UI) show this message, never crash on it.

    `prompt` (the user's raw miss query, from src/ui/app.py) is forwarded
    verbatim in the request body -- no sanitization. Acceptable for this
    demo path talking to trusted provider APIs; not a pattern to copy for
    handling untrusted input.
    """
    if provider == "ollama":
        return _generate_ollama(model, prompt)
    if provider == "agnes":
        api_key = _require_env("AGNESAI_API_KEY")
        return _generate_openai_compatible(AGNES_BASE_URL, api_key, model, prompt)
    if provider == "openai_compatible":
        base_url = _require_env("OPENAI_BASE_URL")
        api_key = _require_env("OPENAI_API_KEY")
        return _generate_openai_compatible(base_url, api_key, model, prompt)
    if provider == "gemini":
        api_key = _require_env("GOOGLE_API_KEY")
        return _generate_gemini(api_key, model, prompt)
    raise GenerateError(f"unknown provider: {provider!r}")

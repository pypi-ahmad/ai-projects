"""Model provider adapters: Ollama, Agnes AI, OpenAI-compatible, Gemini.

Every adapter exposes one method, `chat(messages, tools) -> ProviderReply`,
where `messages` is our own generic OpenAI-Chat-Completions-shaped list of
`{"role", "content", ...}` dicts and `tools` is `Registry.list()`'s output.

Native tool-calling vs JSON-in-prompt, and why, per provider:

- **Ollama** -- native. `/api/chat` accepts a `tools` array in the exact
  OpenAI shape and returns `message.tool_calls`; verified against
  docs.ollama.com/api/chat. Whether a specific allowed model
  (granite4.1:3b, qwen3.5:2b, ...) reliably *uses* tool calling is a
  model-quality question this adapter can't verify -- the wire protocol
  is what's confirmed.
- **OpenAI-compatible** (gpt-5.6-luna/terra) -- native, via the standard
  Chat Completions `tools`/`tool_calls` shape (verified against
  openai-python v2.11.0 in Phase 2/3). Assumed supported because the
  endpoint is documented as OpenAI-compatible; unverified against this
  specific deployment.
- **Agnes AI** (agnes-2.5-flash) -- JSON-in-prompt. No public docs found
  for this endpoint's tool-calling support, so this adapter doesn't
  gamble on the `tools` param silently being ignored (which would mean
  tool calls never fire, with no error to notice). Tool schemas are
  folded into a system message instead and the whole reply is passed to
  `parse.try_extract_call` as plain text.
- **Gemini** (gemini-3.5-flash-lite/3.7-flash) -- native, via the
  official `google-genai` SDK rather than hand-rolled REST: unlike the
  other three (simple, stable, OpenAI-shaped JSON), Gemini's function-
  calling wire format is a distinct protocol (camelCase REST fields,
  `functionCall`/`functionResponse` content parts) that isn't "a few
  lines" to get right safely -- using the official SDK here is the
  correct choice, not a shortcut around one.

Raw HTTP (via `requests`, already a project dependency through Streamlit)
is used for Ollama/OpenAI-compatible/Agnes since their wire protocol is
simple and already verified; no new dependency needed for those three.

Next: api.py, which selects one of these via `get_provider()` per request.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import requests

_DEFAULT_TIMEOUT_S = 60.0


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        msg = f"missing environment variable: {name}"
        raise RuntimeError(msg)
    return value


@dataclass(frozen=True, slots=True)
class ProviderReply:
    """One model turn. `native_tool_calls` is None for JSON-in-prompt providers."""

    text: str | None
    native_tool_calls: list[dict[str, Any]] | None = None


class Provider(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderReply: ...


# --- shared: OpenAI-compatible Chat Completions REST call -------------------


def _post_chat_completions(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    timeout_s: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=timeout_s
    )
    resp.raise_for_status()
    return resp.json()


def _inject_json_in_prompt(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not tools:
        return messages
    tool_lines = "\n".join(
        f'- {t["function"]["name"]}: {t["function"]["description"]} '
        f'(args schema: {json.dumps(t["function"]["parameters"])})'
        for t in tools
    )
    instruction = (
        "You may call one of these tools if it helps answer the request:\n"
        f"{tool_lines}\n\n"
        'To call a tool, reply with ONLY this JSON, nothing else: '
        '{"tool": "<name>", "args": {...}}\n'
        "Otherwise, just answer normally in plain text."
    )
    return [{"role": "system", "content": instruction}, *messages]


# --- Ollama ------------------------------------------------------------------


class OllamaProvider:
    def __init__(
        self, *, model: str = "granite4.1:3b", host: str | None = None, timeout_s: float = _DEFAULT_TIMEOUT_S
    ) -> None:
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderReply:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        message = resp.json().get("message", {})
        return ProviderReply(
            text=message.get("content") or None, native_tool_calls=message.get("tool_calls") or None
        )


# --- OpenAI-compatible (gpt-5.6-luna / gpt-5.6-terra) ------------------------


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        model: str = "gpt-5.6-luna",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.model = model
        self.base_url = base_url or _require_env("OPENAI_BASE_URL")
        self.api_key = api_key or _require_env("OPENAI_API_KEY")
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderReply:
        data = _post_chat_completions(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            tools=tools,
            timeout_s=self.timeout_s,
        )
        message = data["choices"][0]["message"]
        return ProviderReply(text=message.get("content"), native_tool_calls=message.get("tool_calls") or None)


# --- Agnes AI (JSON-in-prompt) ------------------------------------------------


class AgnesProvider:
    BASE_URL = "https://apihub.agnes-ai.com/v1"
    MODEL = "agnes-2.5-flash"

    def __init__(self, *, api_key: str | None = None, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self.api_key = api_key or _require_env("AGNESAI_API_KEY")
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderReply:
        prompted = _inject_json_in_prompt(messages, tools)
        data = _post_chat_completions(
            base_url=self.BASE_URL,
            api_key=self.api_key,
            model=self.MODEL,
            messages=prompted,
            tools=None,
            timeout_s=self.timeout_s,
        )
        message = data["choices"][0]["message"]
        return ProviderReply(text=message.get("content"), native_tool_calls=None)


# --- Gemini (google-genai SDK) ------------------------------------------------


class GeminiProvider:
    def __init__(
        self, *, model: str = "gemini-3.5-flash-lite", api_key: str | None = None
    ) -> None:
        from google import genai  # deferred: only needed if this provider is used

        self.model = model
        self._client = genai.Client(api_key=api_key or _require_env("GOOGLE_API_KEY"))

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderReply:
        from google.genai import types

        contents = _to_gemini_contents(types, messages)
        config = None
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t["function"]["name"],
                    description=t["function"]["description"],
                    parameters_json_schema=t["function"]["parameters"],
                )
                for t in tools
            ]
            config = types.GenerateContentConfig(tools=[types.Tool(function_declarations=declarations)])

        response = self._client.models.generate_content(model=self.model, contents=contents, config=config)
        calls = list(getattr(response, "function_calls", None) or [])
        if calls:
            native = [{"function": {"name": c.name, "arguments": dict(c.args or {})}} for c in calls]
            return ProviderReply(text=None, native_tool_calls=native)
        return ProviderReply(text=response.text, native_tool_calls=None)


def _to_gemini_contents(types: Any, messages: list[dict[str, Any]]) -> list[Any]:
    """Translate our generic messages into Gemini `Content` turns.

    Best-effort mapping for the turn shapes loop.py actually produces
    (user text, assistant text, assistant tool-call, tool result) --
    unverified against a live Gemini call (see providers.py module note).
    """
    contents: list[Any] = []
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            contents.append(
                types.Content(
                    role="tool",
                    parts=[
                        types.Part.from_function_response(
                            name=msg.get("name", "unknown_tool"),
                            response={"result": msg.get("content")},
                        )
                    ],
                )
            )
        elif role == "assistant":
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=msg.get("content") or "")]))
        else:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=msg.get("content") or "")]))
    return contents


_FACTORIES = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatibleProvider,
    "agnes": AgnesProvider,
    "gemini": GeminiProvider,
}


def get_provider(name: str = "ollama", **kwargs: Any) -> Provider:
    """name in {"ollama", "openai", "agnes", "gemini"}."""
    try:
        factory = _FACTORIES[name]
    except KeyError:
        msg = f"unknown provider: {name!r} (expected one of {sorted(_FACTORIES)})"
        raise ValueError(msg) from None
    return factory(**kwargs)

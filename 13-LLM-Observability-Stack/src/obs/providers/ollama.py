"""Ollama adapter: POST http://localhost:11434/api/chat, non-streaming.

Verified against https://github.com/ollama/ollama/blob/main/docs/api.md -
response fields are message.content, prompt_eval_count, prompt_eval_duration
(ns), eval_count, eval_duration (ns). ttft_ms is approximated from
prompt_eval_duration (time spent on the prompt before generation starts) -
a non-streaming call has no real first-token timestamp.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from obs.providers.base import CompletionResult

DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaAdapter:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 60.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]], model: str) -> CompletionResult:
        payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            msg = f"Ollama request to {self.base_url} failed: {exc}"
            raise RuntimeError(msg) from exc

        prompt_eval_duration_ns = body.get("prompt_eval_duration")
        ttft_ms = (
            prompt_eval_duration_ns / 1_000_000 if prompt_eval_duration_ns is not None else None
        )
        return CompletionResult(
            text=body.get("message", {}).get("content", ""),
            in_tokens=body.get("prompt_eval_count"),
            out_tokens=body.get("eval_count"),
            ttft_ms=ttft_ms,
        )

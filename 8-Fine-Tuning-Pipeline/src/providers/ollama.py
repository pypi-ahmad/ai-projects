"""HTTP client for a locally running Ollama server. This is the only place
http://localhost:11434 is hardcoded. Sends no auth header — if Ollama were configured to require
one, this client would not send it. Open cloud.py next for the cloud-model counterpart."""

import requests


class OllamaTeacher:
    """Local Ollama model, called via its HTTP API (no ollama-python dependency needed)."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model_name, "prompt": prompt, "stream": False},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    def chat(self, system: str, user: str, temperature: float = 0.0, think: bool = False) -> str:
        # Ollama applies the model's chat template server-side to these system/user strings.
        # src/eval/bakeoff.py's LocalAdapterModel.chat sends the same two strings but applies the
        # tokenizer's chat template client-side instead — different code path, same input shape.
        # think=False: thinking-capable models (e.g. qwen3.5) otherwise put the answer in a
        # separate `message.thinking` field and can leave `content` empty if generation is cut
        # off mid-thought. We score `content` only, so keep thinking off by default.
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": think,
                "options": {"temperature": temperature},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

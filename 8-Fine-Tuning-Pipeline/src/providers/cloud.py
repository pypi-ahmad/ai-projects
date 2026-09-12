"""HTTP client for any OpenAI-Chat-Completions-compatible endpoint. Assumes the target actually
implements that shape (verified for Agnes AI and OpenAI, the only two entries in
src/providers/__init__.py); a different provider would need its own client if its
request/response shape differs. Trust boundary: the API key leaves this process only in the
Authorization header of the one request below."""

import os

import requests


class OpenAICompatTeacher:
    """Chat-Completions-compatible cloud teacher (Agnes AI, OpenAI, ...).

    Reads its API key from the environment at call time; never logs or persists it.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        timeout: float = 60.0,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"required environment variable {self.api_key_env} is unavailable; "
                "relaunch the host if it was recently configured."
            )
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

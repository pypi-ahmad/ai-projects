"""The two shapes every model client in this repo satisfies, structurally (Protocol, not a base
class) — OllamaTeacher, OpenAICompatTeacher, and src/eval/bakeoff.py's LocalAdapterModel don't
inherit from these, they just implement the matching methods. Open ollama.py next."""

from typing import Protocol


class TeacherClient(Protocol):
    """Anything that can turn a prompt into a raw text completion."""

    model_name: str

    def complete(self, prompt: str) -> str: ...


class ChatClient(Protocol):
    """Anything that can answer a system+user turn, e.g. for prompt-only eval."""

    model_name: str

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str: ...

"""Registry mapping a model name to a concrete client. This is the only place that wires a name
to a class + endpoint; it must not contain client construction logic itself (that lives in
ollama.py/cloud.py). Open base.py next for the two Protocols every client here satisfies."""

from src.providers.base import TeacherClient
from src.providers.cloud import OpenAICompatTeacher
from src.providers.ollama import OllamaTeacher

# Closed registry, not a plugin system: adding a model means adding an entry here, not a config
# file. The two cloud entries are the only places the Agnes AI / OpenAI endpoint URLs appear.
_TEACHER_FACTORIES = {
    "granite4.1:3b": lambda: OllamaTeacher("granite4.1:3b"),
    "qwen3.5:0.8b": lambda: OllamaTeacher("qwen3.5:0.8b"),
    "qwen3.5:2b": lambda: OllamaTeacher("qwen3.5:2b"),
    "agnes-2.5-flash": lambda: OpenAICompatTeacher(
        "agnes-2.5-flash", "https://apihub.agnes-ai.com/v1", "AGNESAI_API_KEY"
    ),
    "gpt-5.6-luna": lambda: OpenAICompatTeacher(
        "gpt-5.6-luna", "https://api.openai.com/v1", "OPENAI_API_KEY"
    ),
}


def get_teacher(name: str) -> TeacherClient:
    """Look up a teacher/repair model client by its Ollama tag or cloud model name."""
    try:
        return _TEACHER_FACTORIES[name]()
    except KeyError:
        raise ValueError(
            f"unknown teacher {name!r}; choices: {sorted(_TEACHER_FACTORIES)}"
        ) from None

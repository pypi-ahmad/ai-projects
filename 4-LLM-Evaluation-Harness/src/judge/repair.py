"""One JSON-repair pass for a malformed judge response: try the small local
qwen3.5:0.8b repair model on Ollama first, falling back to the primary
judge's own provider+model if the local repair model is unavailable.
"""

from src.providers import PROVIDERS
from src.providers.base import Provider, Unloadable

REPAIR_PROVIDER_NAME = "ollama"
REPAIR_MODEL = "qwen3.5:0.8b"


def _build_repair_prompt(broken_text: str, schema_hint: str) -> str:
    return (
        "The following text was supposed to be a single JSON object matching this "
        f"shape, but it is not valid JSON:\n{schema_hint}\n\n"
        f"Broken text:\n{broken_text}\n\n"
        "Return ONLY the corrected JSON object. No prose, no code fences."
    )


def repair_json(
    broken_text: str,
    *,
    schema_hint: str,
    fallback_provider: Provider,
    fallback_model: str,
) -> str | None:
    prompt = _build_repair_prompt(broken_text, schema_hint)

    try:
        repair_provider = PROVIDERS[REPAIR_PROVIDER_NAME].factory()
        result = repair_provider.complete(
            system=None, user=prompt, model=REPAIR_MODEL, think=False
        )
        if isinstance(repair_provider, Unloadable):
            repair_provider.unload(REPAIR_MODEL)
        return result
    except Exception:
        pass  # local repair model unavailable -- fall back to the judge's own provider/model

    try:
        return fallback_provider.complete(
            system=None, user=prompt, model=fallback_model, think=False
        )
    except Exception:
        return None

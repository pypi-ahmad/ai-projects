"""Compression and distillation. Both LLM calls are optional: if the
provider errors, compress() falls back to an extractive summary, and
distill() degrades to zero facts. Neither raises -- Orchestrator.tick()
must keep working with Ollama down (see docs/RUNBOOK.md).

The actual model calls go through an injectable `chat_fn(model, prompt,
format) -> str`, so tests can fake the LLM without needing Ollama up.

Must not: let a Compressor/Distiller exception reach the caller --
Orchestrator.tick() has to keep running with Ollama down (see
docs/RUNBOOK.md); every model call in this file is inside a try/except
that degrades instead of raising.

Next: src/memory/orchestrator.py -- the only caller of Compressor/Distiller.
"""

import json
import re

import ollama
from pydantic import BaseModel, Field, ValidationError

from memory import config
from memory.episodic import Episode

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _ollama_chat(model: str, prompt: str, format: dict | str | None = None) -> str:
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format=format,
    )
    return response.message.content or ""


def _extractive_fallback(text: str) -> str:
    # ponytail: naive sentence split (no abbreviation handling e.g. "Mr.");
    # fine for a fallback path, upgrade to a real sentence tokenizer if
    # fallback quality ever matters more than "provider was down".
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if len(sentences) <= 1:
        return text.strip()
    return f"{sentences[0]} {sentences[-1]}"


class CompressResult(BaseModel):
    text: str
    reason: str  # "llm_summary" or "EXTRACTIVE_FALLBACK"


class Compressor:
    """Summarizes evicted working-memory items into one episodic string."""

    def __init__(self, model: str = config.COMPRESS_MODEL_DEFAULT, chat_fn=None) -> None:
        self._model = model
        self._chat_fn = chat_fn or _ollama_chat

    def compress(self, texts: list[str]) -> CompressResult:
        joined = "\n".join(texts)
        prompt = (
            "Summarize the following working-memory items into one concise "
            "paragraph for long-term episodic storage. Preserve concrete "
            "facts, names, and numbers. Do not add commentary or invent "
            "anything not present below.\n\n" + joined
        )
        try:
            text = self._chat_fn(self._model, prompt).strip()
            if not text:
                raise ValueError("empty completion")
            return CompressResult(text=text, reason="llm_summary")
        except Exception:
            return CompressResult(text=_extractive_fallback(joined), reason="EXTRACTIVE_FALLBACK")


class DistillResult(BaseModel):
    """0-5 fact strings distilled from a batch of episodes. 0 is valid --
    an empty batch shouldn't pressure the model into inventing a fact."""

    facts: list[str] = Field(default_factory=list, max_length=5)


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip())


def _parse_distill_json(raw: str) -> DistillResult | None:
    try:
        data = json.loads(_strip_fences(raw))
        return DistillResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None


class Distiller:
    """Distills recent episodes into a handful of standalone facts."""

    def __init__(self, model: str = config.COMPRESS_MODEL_DEFAULT, chat_fn=None) -> None:
        self._model = model
        self._chat_fn = chat_fn or _ollama_chat

    def distill(self, episodes: list[Episode]) -> DistillResult:
        if not episodes:
            return DistillResult(facts=[])
        transcript = "\n".join(f"[{e.type}] {e.text}" for e in episodes)
        schema = DistillResult.model_json_schema()
        prompt = (
            "Extract at most 5 standalone facts worth remembering long-term "
            "from this transcript. Use only entities, names, and numbers "
            "that already appear below -- never invent a new one. If "
            "nothing is worth keeping, return an empty list.\n\n"
            f"{transcript}\n\n"
            'Respond with JSON only: {"facts": ["...", ...]}'
        )
        try:
            raw = self._chat_fn(self._model, prompt, schema)
        except Exception:
            return DistillResult(facts=[])  # provider down: distill is a no-op, not a crash

        result = _parse_distill_json(raw)
        if result is not None:
            return result

        # Invalid JSON: exactly one repair attempt, always with the default
        # compress model regardless of what self._model was.
        repair_prompt = (
            "The following was supposed to be JSON matching "
            f'{{"facts": [string, ...]}} (at most 5 items) but failed to parse:\n\n'
            f"{raw}\n\nReturn corrected JSON only, no commentary."
        )
        try:
            repaired = self._chat_fn(config.COMPRESS_MODEL_DEFAULT, repair_prompt, schema)
        except Exception:
            return DistillResult(facts=[])
        return _parse_distill_json(repaired) or DistillResult(facts=[])

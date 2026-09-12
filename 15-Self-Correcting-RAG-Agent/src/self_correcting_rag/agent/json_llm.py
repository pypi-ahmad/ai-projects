"""Calls a Provider and validates its response as JSON against a Pydantic
schema, with exactly one repair attempt (re-ask the model to fix its own
output) before giving up. No unbounded retry loop.
"""

import re

from pydantic import BaseModel, ValidationError

from self_correcting_rag.llm.base import Provider

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BRACE_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strips a markdown code fence or leading/trailing prose around a JSON
    object, since models sometimes wrap JSON that way despite instructions.
    """
    text = text.strip()
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        return fence_match.group(1)
    brace_match = _BRACE_RE.search(text)
    return brace_match.group(0) if brace_match else text


def call_json[ModelT: BaseModel](
    provider: Provider, *, system: str, user: str, model: str, schema: type[ModelT]
) -> ModelT:
    raw = provider.complete(system=system, user=user, model=model)
    try:
        return schema.model_validate_json(_extract_json(raw))
    except (ValueError, ValidationError) as first_error:
        repair_user = (
            "Your previous response was not valid JSON matching the required schema.\n"
            f"Error: {first_error}\n\nYour previous response was:\n{raw}\n\n"
            "Return ONLY corrected JSON matching the schema. No other text, no markdown fences."
        )
        repaired_raw = provider.complete(system=system, user=repair_user, model=model)
        return schema.model_validate_json(_extract_json(repaired_raw))

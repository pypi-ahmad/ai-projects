"""The product: text + schema -> StructuredResult, actually wired to a real
provider via the `providers.complete()` interface (Phase 3). The Phase 1
`StructuredOutputEngine` this superseded was deleted (Phase 8) — it was
never connected to any real provider.

Attempt ladder (default max_attempts=3):
  1. initial  — primary provider/model, normal temperature.
  2. retry    — same provider/model, lower temperature, validator errors fed back.
  3. repair   — switch to repair_model (default: local Ollama qwen3.5:0.8b,
                even if the initial pass used a different provider) unless
                `pin_provider=True`, in which case repair reuses the primary
                provider/model too.
Attempts beyond 3 (only if max_attempts is raised) keep repeating the
"repair" strategy against the most recent failure.

A provider exception (network/auth/timeout) is treated as a failed attempt
like a validation failure — it still consumes an attempt and can be
followed by a retry/repair, which matters when the *initial* provider is
down but the repair provider (a different one, by default) is not. This is
a deliberate difference from Phase 1's engine, which never retried a
provider error.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from providers.base import Provider, ProviderError
from providers.ollama_provider import OllamaProvider

from .result import StructuredResult, ValidationIssue

logger = logging.getLogger(__name__)

DEFAULT_REPAIR_MODEL = "qwen3.5:0.8b"
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ParseError(Exception):
    """Nothing resembling a JSON object was found in the reply at all."""


class PipelineFailure(Exception):
    """Raised only when fallback="raise" (CLI --strict). Callers at the
    process edge (see engine/__main__.py) are expected to catch this."""

    def __init__(self, result: StructuredResult) -> None:
        self.result = result
        super().__init__(f"pipeline failed after {result.attempts} attempt(s): {result.errors}")


# --------------------------------------------------------------------------
# Message building
# --------------------------------------------------------------------------


def build_messages(text: str, json_schema: dict) -> list[dict[str, str]]:
    system = (
        "You are a strict data-extraction engine. Read the user's text and produce a "
        "single JSON object that matches the JSON Schema below exactly: every required "
        "field present, every type and enum value correct, no fields beyond what the "
        "schema allows unless it permits them. Return only one JSON object — no markdown "
        f"fences, no explanation, no surrounding text.\n\nJSON Schema:\n{json.dumps(json_schema)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def build_retry_messages(
    text: str, json_schema: dict, errors: list[ValidationIssue], raw_text: str
) -> list[dict[str, str]]:
    messages = build_messages(text, json_schema)
    messages.append({"role": "assistant", "content": raw_text})
    messages.append(
        {
            "role": "user",
            "content": (
                f"That output failed validation:\n{_format_errors(errors)}\n\n"
                "Return corrected JSON that matches the schema exactly. A single JSON "
                "object only — no markdown, no explanation."
            ),
        }
    )
    return messages


def build_repair_messages(
    raw_text: str, json_schema: dict, errors: list[ValidationIssue]
) -> list[dict[str, str]]:
    system = (
        "You are a JSON repair tool. You will be given malformed or schema-invalid "
        "output, the validation errors it produced, and the JSON Schema it must match. "
        "Return only the corrected JSON object — no markdown, no explanation, no "
        f"surrounding text.\n\nJSON Schema:\n{json.dumps(json_schema)}"
    )
    user = f"Malformed output:\n{raw_text}\n\n{_format_errors(errors)}\n\nReturn corrected JSON only."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _format_errors(errors: list[ValidationIssue]) -> str:
    lines = [f"- {'.'.join(map(str, e.loc)) or '(root)'}: {e.msg} [{e.type}]" for e in errors]
    return "Validation errors:\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------


def extract_json(raw: str) -> str:
    """Best-effort extraction of a JSON object substring from a model reply:
    the whole reply, a fenced code block, or the first balanced {...} span,
    in that order. A syntactically-broken candidate is still returned (the
    caller's schema validation will report the specific defect) — this
    raises ParseError only when nothing resembling a JSON object is found
    at all (e.g. a plain-prose refusal)."""
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    fence_match = _FENCE_RE.search(raw)
    if fence_match and fence_match.group(1).strip():
        return fence_match.group(1).strip()

    span = _find_first_json_object(raw)
    if span is not None:
        return span

    raise ParseError(f"No JSON object found in the model's reply: {raw[:200]!r}")


def _find_first_json_object(text: str) -> str | None:
    """First balanced {...} span, respecting string literals so a brace
    inside a quoted string doesn't throw off the depth count."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# --------------------------------------------------------------------------
# Graceful fallback (fallback="partial")
# --------------------------------------------------------------------------


def build_partial(raw_text: str, schema: type[BaseModel]) -> tuple[BaseModel | dict, list[ValidationIssue]]:
    """Keep whichever fields independently validate against their own type;
    for the rest, use the schema's default when the field has one (i.e. it
    isn't truly required) and leave it out otherwise — a still-missing
    required field is reported back in the returned errors, never
    fabricated."""
    try:
        raw = json.loads(raw_text) if raw_text else {}
        if not isinstance(raw, dict):
            raw = {}
    except json.JSONDecodeError:
        raw = {}

    kept: dict[str, Any] = {}
    remaining_errors: list[ValidationIssue] = []

    for name, field in schema.model_fields.items():
        if name in raw:
            try:
                kept[name] = TypeAdapter(field.annotation).validate_python(raw[name])
                continue
            except ValidationError as exc:
                first = exc.errors()[0]
                issue = ValidationIssue(loc=(name,), msg=first["msg"], type=first["type"])
        else:
            issue = ValidationIssue(loc=(name,), msg="Field required", type="missing")

        # Missing/invalid but not required -> silently take the schema's own
        # default; only a truly required field surfaces as a remaining error.
        if field.is_required():
            remaining_errors.append(issue)
        else:
            kept[name] = field.get_default(call_default_factory=True)

    try:
        return schema.model_validate(kept), remaining_errors
    except ValidationError:
        return kept, remaining_errors


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


@dataclass
class Pipeline:
    provider: Provider
    model: str
    repair_provider: Provider | None = None
    repair_model: str = DEFAULT_REPAIR_MODEL
    pin_provider: bool = False
    max_attempts: int = 3
    fallback: str = "partial"  # "partial" | "empty" | "raise"
    temperature: float = 0.2
    repair_temperature: float = 0.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.fallback not in ("partial", "empty", "raise"):
            raise ValueError(f"fallback must be 'partial', 'empty', or 'raise', got {self.fallback!r}")
        self._lazy_repair_provider: Provider | None = None

    def run(self, text: str, schema: type[BaseModel]) -> StructuredResult:
        json_schema = schema.model_json_schema()
        messages = build_messages(text, json_schema)

        attempt = 1
        stage = "initial"
        provider, model, temperature = self.provider, self.model, self.temperature
        result: StructuredResult | None = None

        while True:
            started = time.monotonic()
            try:
                response = provider.complete(
                    messages, json_schema=json_schema, temperature=temperature, max_tokens=self.max_tokens
                )
            except ProviderError as exc:
                latency_ms = _elapsed_ms(started)
                result = StructuredResult.from_provider_error(
                    exc, attempts=attempt, model=model, provider=_provider_name(provider), latency_ms=latency_ms
                )
                self._log(attempt, stage, model, _provider_name(provider), "", result, latency_ms)
            else:
                latency_ms = _elapsed_ms(started)
                try:
                    json_text = extract_json(response.text)
                except ParseError as exc:
                    result = StructuredResult(
                        ok=False,
                        data=None,
                        errors=[ValidationIssue(loc=(), msg=str(exc), type="parse_error")],
                        raw_text=response.text,
                        attempts=attempt,
                        model=model,
                        provider=_provider_name(provider),
                        latency_ms=latency_ms,
                    )
                else:
                    result = StructuredResult.from_raw_text(
                        json_text, schema, attempts=attempt, model=model,
                        provider=_provider_name(provider), latency_ms=latency_ms,
                    )
                self._log(attempt, stage, model, _provider_name(provider), response.text, result, latency_ms)

            if result.ok:
                return result
            if attempt >= self.max_attempts:
                break

            attempt += 1
            if attempt == 2:
                stage = "retry"
                temperature = self.repair_temperature
                messages = build_retry_messages(text, json_schema, result.errors, result.raw_text)
            else:
                stage = "repair"
                old_provider, old_model = provider, model
                provider, model = self._repair_provider_and_model()
                if provider is not old_provider and hasattr(old_provider, "unload"):
                    # Free VRAM before the repair model loads (NOTES.md: one
                    # heavy model at a time). Best-effort — a failed unload
                    # shouldn't block the repair attempt.
                    try:
                        old_provider.unload(old_model)
                    except Exception:
                        pass
                temperature = self.repair_temperature
                messages = build_repair_messages(result.raw_text, json_schema, result.errors)

        return self._apply_fallback(result, schema)

    def _repair_provider_and_model(self) -> tuple[Provider, str]:
        if self.pin_provider:
            return self.provider, self.model
        if self.repair_provider is not None:
            return self.repair_provider, self.repair_model
        if self._lazy_repair_provider is None:
            self._lazy_repair_provider = OllamaProvider(self.repair_model)
        return self._lazy_repair_provider, self.repair_model

    def _apply_fallback(self, result: StructuredResult, schema: type[BaseModel]) -> StructuredResult:
        if self.fallback == "raise":
            raise PipelineFailure(result)
        if self.fallback == "empty":
            return StructuredResult(
                ok=False, data=None, errors=result.errors, raw_text=result.raw_text,
                attempts=result.attempts, model=result.model, provider=result.provider,
                latency_ms=result.latency_ms,
            )
        data, errors = build_partial(result.raw_text, schema)
        return StructuredResult(
            ok=False, data=data, errors=errors, raw_text=result.raw_text,
            attempts=result.attempts, model=result.model, provider=result.provider,
            latency_ms=result.latency_ms,
        )

    @staticmethod
    def _log(
        attempt: int, stage: str, model: str, provider_name: str, raw_text: str,
        result: StructuredResult, latency_ms: float,
    ) -> None:
        snippet = raw_text[:200].replace("\n", " ")
        logger.info(
            "attempt=%d stage=%s provider=%s model=%s ok=%s latency_ms=%.1f errors=%s raw=%r",
            attempt, stage, provider_name, model, result.ok, latency_ms,
            [e.type for e in result.errors], snippet,
        )


def _provider_name(provider: Provider) -> str:
    return type(provider).__name__


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000

"""Single result envelope for a structured-output attempt.

`ok=False` never means an exception leaked to the caller — it means `errors`
holds exactly what went wrong, each shaped like a pydantic ValidationError
entry (loc, msg, type). A provider failure (network, auth, timeout) is
reported the same way, with `type="provider_error"`, so callers only ever
need to branch on `ok` and walk one `errors` list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ValidationIssue:
    loc: tuple[int | str, ...]
    msg: str
    type: str


@dataclass(frozen=True)
class StructuredResult:
    ok: bool
    data: BaseModel | dict | None  # dict only from a "partial" fallback that couldn't form a full instance
    errors: list[ValidationIssue] = field(default_factory=list)
    raw_text: str = ""
    attempts: int = 1
    model: str | None = None
    provider: str | None = None
    latency_ms: float | None = None

    @classmethod
    def from_raw_text(
        cls,
        raw_text: str,
        schema: type[BaseModel],
        *,
        attempts: int = 1,
        model: str | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> StructuredResult:
        """Parse + validate `raw_text` against `schema` in one step."""
        try:
            data = schema.model_validate_json(raw_text)
        except ValidationError as exc:
            return cls(
                ok=False,
                data=None,
                errors=[
                    ValidationIssue(loc=tuple(e["loc"]), msg=e["msg"], type=e["type"])
                    for e in exc.errors()
                ],
                raw_text=raw_text,
                attempts=attempts,
                model=model,
                provider=provider,
                latency_ms=latency_ms,
            )
        return cls(
            ok=True,
            data=data,
            raw_text=raw_text,
            attempts=attempts,
            model=model,
            provider=provider,
            latency_ms=latency_ms,
        )

    @classmethod
    def from_provider_error(
        cls,
        exc: Exception,
        *,
        attempts: int = 1,
        model: str | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> StructuredResult:
        return cls(
            ok=False,
            data=None,
            errors=[ValidationIssue(loc=(), msg=str(exc), type="provider_error")],
            raw_text="",
            attempts=attempts,
            model=model,
            provider=provider,
            latency_ms=latency_ms,
        )

"""Execute a RouteDecision: call providers in fallback order, stop on first success.

Contract with src/providers/*.py: every complete() must raise ProviderError
(or MissingKeyError) for any failure, since the loop below only catches
ProviderError — any other exception type propagates and aborts the request
instead of advancing to the next fallback target.
"""
from __future__ import annotations
import json
import time
import tiktoken
from typing import Callable, Optional

from ..gateway.models import (
    AttemptRecord,
    GatewayRequest,
    GatewayResponse,
    RouteDecision,
    UsageRecord,
)
from ..providers.base import ProviderError, ProviderResult

ProviderFn = Callable[[str, str, GatewayRequest, int], ProviderResult]

_enc = tiktoken.get_encoding("cl100k_base")


def _approx(prompt: str, response: str) -> tuple[int, int]:
    return len(_enc.encode(prompt)), len(_enc.encode(response))


def _real_provider(
    provider: str, model: str, request: GatewayRequest, timeout_s: int
) -> ProviderResult:
    if provider == "ollama":
        from ..providers.ollama import complete
        return complete(request, model, timeout_s, _approx)
    if provider == "agnes":
        from ..providers.agnes import complete
        return complete(request, model, timeout_s, _approx)
    if provider == "openai":
        from ..providers.openai_compat import complete
        return complete(request, model, timeout_s, _approx)
    if provider == "gemini":
        from ..providers.gemini import complete
        return complete(request, model, timeout_s, _approx)
    raise ProviderError(f"unknown provider: {provider}")


def _timeout_for(provider: str, model: str, tiers_cfg: dict) -> int:
    for tier_data in tiers_cfg.get("tiers", {}).values():
        for t in tier_data.get("targets", []):
            if t["provider"] == provider and t["model"] == model:
                return int(t.get("timeout_s", 60))
    return 60


def _tier_for(provider: str, model: str, tiers_cfg: dict) -> Optional[str]:
    for tier_name, tier_data in tiers_cfg.get("tiers", {}).items():
        for t in tier_data.get("targets", []):
            if t["provider"] == provider and t["model"] == model:
                return tier_name
    return None


def execute(
    decision: RouteDecision,
    request: GatewayRequest,
    tiers_cfg: dict,
    provider_fn: Optional[ProviderFn] = None,
) -> GatewayResponse:
    if decision.status != "ok":
        return GatewayResponse(ok=False, error=f"routing: {decision.status}")

    call = provider_fn or _real_provider
    all_targets = [f"{decision.provider}:{decision.model}"] + list(decision.fallback_chain)
    attempts: list[AttemptRecord] = []

    for entry in all_targets:
        # Reverses the "provider:model" encoding route/router.py builds for
        # decision.provider/model and fallback_chain entries.
        provider, _, model = entry.partition(":")
        timeout_s = _timeout_for(provider, model, tiers_cfg)
        tier = _tier_for(provider, model, tiers_cfg) or decision.tier

        t0 = time.monotonic()
        try:
            result = call(provider, model, request, timeout_s)
            latency_ms = (time.monotonic() - t0) * 1000

            if not result.text.strip():
                raise ProviderError("empty response")
            if request.need_json:
                try:
                    json.loads(result.text)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"invalid JSON: {exc}") from exc

            attempts.append(AttemptRecord(
                provider=provider, model=model, ok=True, latency_ms=latency_ms
            ))
            return GatewayResponse(
                text=result.text,
                tier_used=tier,
                model=model,
                provider=provider,
                attempts=attempts,
                usage=UsageRecord(
                    in_tokens=result.in_tokens,
                    out_tokens=result.out_tokens,
                    approximate=result.approximate,
                ),
                ok=True,
            )
        except ProviderError as exc:
            # A failed attempt against a paid provider (e.g. "invalid JSON" or
            # "empty response", both raised only after the provider actually
            # generated output) may still have been billed by that provider —
            # AttemptRecord does not carry token counts, so that cost is never
            # reflected in cost_by_tier/cost_sum. Only the final successful
            # attempt's usage is recorded.
            latency_ms = (time.monotonic() - t0) * 1000
            attempts.append(AttemptRecord(
                provider=provider, model=model, ok=False,
                error=str(exc), latency_ms=latency_ms,
            ))

    return GatewayResponse(ok=False, error="all targets exhausted", attempts=attempts)

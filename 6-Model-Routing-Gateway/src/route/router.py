"""Model router: reads tiers config, checks availability at decision time, returns RouteDecision.

No network calls to LLMs here — Phase 4 handles generation.
"""
from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from src.gateway.features import Features
from src.gateway.models import GatewayRequest, ReasonCode, RouteDecision
from src.providers.availability import default_available

# Auto-select order — must match the upward-only promotion order documented
# on gateway.models.TierName. Nothing cross-checks the two; changing one
# without the other silently breaks the "never fall back to a cheaper tier"
# guarantee.
_TIER_ORDER = ["lite", "mid", "heavy"]
AvailabilityFn = Callable[[str, str], bool]


def load_tiers(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def route(
    request: GatewayRequest,
    features: Features,
    tiers_cfg: dict[str, Any],
    availability_fn: AvailabilityFn | None = None,
) -> RouteDecision:
    """Return a RouteDecision without making any LLM calls.

    availability_fn(provider, model) -> bool  — inject a fake in tests.
    Default: checks env vars + Ollama /api/tags at decision time.
    """
    if availability_fn is None:
        availability_fn = default_available

    tiers = tiers_cfg.get("tiers", {})
    reason_codes: list[ReasonCode] = []

    # ── candidate tier ordering ──────────────────────────────────────────────
    # Preferred mode: try preferred tier then its configured fallbacks (upward only).
    # Auto-select mode: iterate lite → mid → heavy.
    if request.preferred_tier and request.preferred_tier not in request.disallow_tiers:
        preferred = request.preferred_tier
        pref_fallbacks = tiers.get(preferred, {}).get("fallbacks", [])
        candidate_tiers = [preferred] + [
            t for t in pref_fallbacks if t not in request.disallow_tiers
        ]
        preferred_mode = True
    else:
        candidate_tiers = [t for t in _TIER_ORDER if t not in request.disallow_tiers]
        preferred_mode = False

    # ── try each tier in order ───────────────────────────────────────────────
    for tier_idx, tier_name in enumerate(candidate_tiers):
        if tier_name not in tiers:
            continue
        targets = tiers[tier_name].get("targets", [])

        for target in targets:
            skip = _skip_reason(request, features, target, tier_name)
            if skip is not None:
                reason_codes.append(skip)
                continue

            if not availability_fn(target["provider"], target["model"]):
                reason_codes.append(ReasonCode.SKIPPED_UNAVAILABLE)
                continue

            # ── target accepted ──────────────────────────────────────────────
            if preferred_mode and tier_idx == 0:
                reason_codes.append(ReasonCode.PREFERRED_TIER_USED)
            elif preferred_mode:
                reason_codes.append(ReasonCode.FALLBACK_FROM_PREFERRED)
            else:
                reason_codes.append(ReasonCode.AUTO_SELECTED)

            return RouteDecision(
                status="ok",
                tier=tier_name,
                provider=target["provider"],
                model=target["model"],
                reason_codes=reason_codes,
                fallback_chain=_fallback_chain(tier_name, target, tier_idx, candidate_tiers, tiers),
            )

    # ── no target found ──────────────────────────────────────────────────────
    # Distinguish a config gap (no vision target exists anywhere, ever) from a
    # transient outage (targets exist but were all unavailable right now) —
    # callers can retry the latter but not the former.
    if request.flags.has_image and not _any_vision_ok(tiers):
        return RouteDecision(status="unsupported", reason_codes=reason_codes)
    return RouteDecision(status="unavailable", reason_codes=reason_codes)


# ── helpers ───────────────────────────────────────────────────────────────────

def _skip_reason(
    request: GatewayRequest,
    features: Features,
    target: dict[str, Any],
    tier_name: str,
) -> ReasonCode | None:
    allowed = target.get("allowed_when", {})
    vision_ok = target.get("vision_ok", False)

    if request.flags.has_image and not vision_ok:
        return ReasonCode.SKIPPED_NO_VISION

    if not (allowed.get("min_score", 0.0) <= features.complexity_score <= allowed.get("max_score", 1.0)):
        return ReasonCode.SKIPPED_SCORE_RANGE

    if any(not getattr(request.flags, f, False) for f in allowed.get("flags", [])):
        return ReasonCode.SKIPPED_FLAG_REQUIRED

    # Hard rule: hard + need_json cannot land on lite
    if tier_name == "lite" and features.complexity_label == "hard" and request.need_json:
        return ReasonCode.SKIPPED_HARD_JSON_LITE

    return None


def _fallback_chain(
    tier_name: str,
    selected: dict[str, Any],
    tier_idx: int,
    candidate_tiers: list[str],
    tiers: dict[str, Any],
) -> list[str]:
    # Encodes each target as "provider:model" — this is the wire format
    # route/executor.py parses back apart with str.partition(":"). Keep the
    # two in sync if this format ever changes.
    chain: list[str] = []
    # Remaining targets in the current tier (after the selected one)
    past = False
    for t in tiers[tier_name].get("targets", []):
        if not past:
            if t["provider"] == selected["provider"] and t["model"] == selected["model"]:
                past = True
        else:
            chain.append(f"{t['provider']}:{t['model']}")
    # Targets in subsequent candidate tiers
    for name in candidate_tiers[tier_idx + 1:]:
        if name in tiers:
            for t in tiers[name].get("targets", []):
                chain.append(f"{t['provider']}:{t['model']}")
    return chain


def _any_vision_ok(tiers: dict[str, Any]) -> bool:
    return any(
        t.get("vision_ok", False)
        for tier in tiers.values()
        for t in tier.get("targets", [])
    )

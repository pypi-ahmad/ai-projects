"""CLI: python -m src.gateway --text "..." [--need-json] [--tier lite|mid|heavy]"""
from __future__ import annotations
import argparse
import json
import sys
import uuid
from pathlib import Path

import yaml

from .features import FeatureExtractor
from .models import GatewayRequest
from ..cost.ledger import load_prices, log_event
from ..providers.availability import default_available
from ..route.executor import execute
from ..route.router import load_tiers, route

_FEATURES_CFG = Path("config/features.yaml")
_TIERS_CFG = Path("config/tiers.yaml")
_PRICES_CFG = Path("config/prices.yaml")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.gateway")
    parser.add_argument("--text", required=True, help="User prompt text")
    parser.add_argument("--need-json", action="store_true", default=False)
    parser.add_argument("--tier", choices=["lite", "mid", "heavy"], default=None)
    parser.add_argument("--system", default=None, help="System prompt")
    args = parser.parse_args()

    with open(_FEATURES_CFG) as fh:
        feat_cfg = yaml.safe_load(fh)
    tiers_cfg = load_tiers(_TIERS_CFG)
    prices = load_prices(_PRICES_CFG)

    request = GatewayRequest(
        id=str(uuid.uuid4()),
        user_text=args.text,
        need_json=args.need_json,
        preferred_tier=args.tier,
        system=args.system,
    )

    extractor = FeatureExtractor(feat_cfg)
    features = extractor.extract(request)
    decision = route(request, features, tiers_cfg, default_available)
    response = execute(decision, request, tiers_cfg)

    # Logged unconditionally, success or failure — the usage log is meant to
    # capture fail_rate/fallback_rate for docs/cost aggregation, so a failed
    # request still needs an event row (with usage/tokens left at 0).
    latency_ms = response.attempts[-1].latency_ms if response.attempts else 0.0
    fallbacks = max(0, len(response.attempts) - 1)
    log_event(
        request_id=request.id,
        tier_planned=decision.tier,
        tier_used=response.tier_used,
        model=response.model,
        provider=response.provider,
        in_tokens=response.usage.in_tokens if response.usage else 0,
        out_tokens=response.usage.out_tokens if response.usage else 0,
        latency_ms=latency_ms,
        fallbacks=fallbacks,
        ok=response.ok,
        reason=response.error,
        prices=prices,
    )

    print(json.dumps({
        "ok": response.ok,
        "tier_used": response.tier_used,
        "provider": response.provider,
        "model": response.model,
        "text": response.text,
        "error": response.error,
        "attempts": [a.model_dump() for a in response.attempts],
        "usage": response.usage.model_dump() if response.usage else None,
    }, indent=2))

    # Exit-code contract: 0 only when a target actually replied successfully.
    # A non-zero exit still prints a full JSON body (attempts, error) on stdout.
    sys.exit(0 if response.ok else 1)


if __name__ == "__main__":
    main()

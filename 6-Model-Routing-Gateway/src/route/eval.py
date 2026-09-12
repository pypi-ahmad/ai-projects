"""Routing eval runner — no LLM calls, no GPU required.

Usage:
    python -m src.route.eval [--fail-on-mismatch] [--cases tests/eval/routes.jsonl]

Exit 0 = all cases pass. Exit 1 = one or more mismatches (when --fail-on-mismatch).
This is the merge gate for routing logic.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import yaml

from src.gateway.features import FeatureExtractor
from src.gateway.models import GatewayRequest, RequestFlags
from src.route.router import load_tiers, route

_CASES_FILE  = Path("tests/eval/routes.jsonl")
_FEATURES_CFG = Path("config/features.yaml")
_TIERS_CFG   = Path("config/tiers.yaml")

_ALL_AVAILABLE = lambda p, m: True  # availability not under test here
# Injected in place of providers.availability.default_available so this eval
# never touches the network (no Ollama /api/tags probe, no env var checks) —
# that keeps it a pure routing-logic check, safe to run as a merge gate on
# any machine, GPU or no GPU, keys set or not.


def _run_case(case: dict, extractor: FeatureExtractor, tiers_cfg: dict) -> dict:
    flags = RequestFlags(**(case.get("flags") or {}))
    request = GatewayRequest(
        id=case["id"],
        user_text=case["user_text"],
        need_json=case.get("need_json", False),
        preferred_tier=case.get("preferred_tier"),
        disallow_tiers=case.get("disallow_tiers", []),
        flags=flags,
    )
    features = extractor.extract(request)
    decision = route(request, features, tiers_cfg, _ALL_AVAILABLE)

    errors: list[str] = []
    if "expected_tier" in case and decision.tier != case["expected_tier"]:
        errors.append(f"tier={decision.tier!r}, expected {case['expected_tier']!r}")
    if "expected_not_tier" in case and decision.tier == case["expected_not_tier"]:
        errors.append(f"tier={decision.tier!r}, expected NOT {case['expected_not_tier']!r}")
    if "expected_model" in case and decision.model != case["expected_model"]:
        errors.append(f"model={decision.model!r}, expected {case['expected_model']!r}")
    if "expected_status" in case and decision.status != case["expected_status"]:
        errors.append(f"status={decision.status!r}, expected {case['expected_status']!r}")

    return {
        "id": case["id"],
        "ok": not errors,
        "tier": decision.tier,
        "model": decision.model,
        "score": features.complexity_score,
        "label": features.complexity_label,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.route.eval")
    parser.add_argument("--fail-on-mismatch", action="store_true",
                        help="Exit 1 if any case fails (use in CI)")
    parser.add_argument("--cases", default=str(_CASES_FILE),
                        help="Path to routes.jsonl (default: tests/eval/routes.jsonl)")
    args = parser.parse_args()

    with open(_FEATURES_CFG, encoding="utf-8") as fh:
        feat_cfg = yaml.safe_load(fh)
    tiers_cfg = load_tiers(_TIERS_CFG)
    extractor = FeatureExtractor(feat_cfg)

    with open(args.cases, encoding="utf-8") as fh:
        cases = [json.loads(ln) for ln in fh if ln.strip()]

    results = [_run_case(c, extractor, tiers_cfg) for c in cases]
    passed  = sum(1 for r in results if r["ok"])
    failed  = len(results) - passed

    for r in results:
        tag = "PASS" if r["ok"] else "FAIL"
        print(f"  [{tag}] {r['id']}"
              f"  tier={r['tier']}, model={r['model']}, "
              f"score={r['score']} ({r['label']})")
        for err in r["errors"]:
            print(f"         ✗ {err}")

    print(f"\n{passed}/{len(results)} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print()

    if args.fail_on_mismatch and failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

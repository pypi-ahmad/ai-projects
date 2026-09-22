"""Opt-in, budgeted Sol resolution comparison on five approved pages only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

from scripts.evaluate_prompts import ROOT, REFERENCES, SAMPLES, run_page, score_page
from src.models import DEFAULT_MODEL
from src.preprocess import preprocess_pages
from src.layout import ParsePage
from src.usage import cost_usd

PROFILES = {"baseline": (200, 1600), "candidate": (300, 3200)}
APPROVED_SAMPLES = SAMPLES[1:]  # Never resubmit the previously filtered BadgeCare page.
MAX_REQUESTS = 10
BUDGET_USD = 2.0
REQUEST_RESERVE_USD = 0.20
MAX_COMPLETION_TOKENS = 8192


def metric_gate(pages: list[dict]) -> bool:
    if len(pages) != 10 or any(p["status"] != "parsed" for p in pages):
        return False
    by_page = {}
    for p in pages:
        by_page.setdefault((p["document"], p["page"]), {})[p["profile"]] = p["metrics"]["reference_token_f1"]
    if len(by_page) != 5 or any(set(scores) != set(PROFILES) for scores in by_page.values()):
        return False
    return (all(s["candidate"] >= s["baseline"] for s in by_page.values())
            and sum(s["candidate"] - s["baseline"] for s in by_page.values()) > 0)


def compare(output: Path, *, runner=None, max_requests: int = MAX_REQUESTS,
            budget_usd: float = BUDGET_USD) -> dict:
    """Called only after explicit live authorization; limits may be lowered, not raised."""
    if not 0 < max_requests <= MAX_REQUESTS or not 0 < budget_usd <= BUDGET_USD:
        raise ValueError("Comparison limits exceed the approved bounds")
    runner = runner or run_page
    prompt_path = ROOT / "prompts/runtime/parse-page.md"
    prompt = prompt_path.read_text(encoding="utf-8").rstrip("\r\n")
    # Check all inputs before any paid calls or output creation.
    references = {}
    for name, _ in APPROVED_SAMPLES:
        if not (ROOT / "data/inbox" / f"{name}.pdf").is_file():
            raise FileNotFoundError(f"Missing approved sample: {name}")
        references[name] = json.loads((REFERENCES / f"{name}.parse.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    (output / "parse-page.md").write_text(prompt, encoding="utf-8")
    manifest = dict(model=DEFAULT_MODEL, profiles=PROFILES, reasoning="medium", detail="auto",
                    max_retries=0, max_parallel_pages=1, max_requests=max_requests,
                    max_completion_tokens=MAX_COMPLETION_TOKENS, budget_usd=budget_usd,
                    request_reserve_usd=REQUEST_RESERVE_USD, estimated_cost_usd=0.0,
                    prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), requests=0,
                    pages=[], metric_gate_passed=False, visual_review="not_started",
                    promoted=False, stop_reason=None)
    started = time.perf_counter()

    def save():
        manifest["seconds"] = time.perf_counter() - started
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    save()
    for name, end in APPROVED_SAMPLES:
        for number in range(1, end + 1):
            for profile, (dpi, edge) in PROFILES.items():
                if manifest["requests"] >= max_requests:
                    manifest["stop_reason"] = "request_limit"
                elif manifest["estimated_cost_usd"] + REQUEST_RESERVE_USD > budget_usd:
                    manifest["stop_reason"] = "estimated_budget"
                if manifest["stop_reason"]:
                    save()
                    return manifest
                payload = preprocess_pages(ROOT / "data/inbox" / f"{name}.pdf",
                                           start_page=number, end_page=number,
                                           pdf_dpi=dpi, max_long_edge=edge)[0]
                filename = f"{name}.page-{number}.{profile}"
                (output / f"{filename}.png").write_bytes(base64.b64decode(payload["base64"]))
                manifest["requests"] += 1
                save()  # Count a dispatched attempt even if interrupted.
                outcome = runner(payload, prompt, max_completion_tokens=MAX_COMPLETION_TOKENS,
                                 reasoning_effort="medium")
                outcome.update(document=name, profile=profile, width=payload["width"], height=payload["height"])
                diagnostic = outcome.get("diagnostics", {})
                if diagnostic.get("usage_known"):
                    cost = cost_usd(dict(input_tokens=diagnostic["input_tokens"],
                                        output_tokens=diagnostic["output_tokens"],
                                        cached_tokens=diagnostic.get("cached_tokens") or 0,
                                        cache_write_tokens=diagnostic.get("cache_write_tokens") or 0))
                    outcome["estimated_cost_usd"] = cost
                    manifest["estimated_cost_usd"] += cost
                else:
                    manifest["stop_reason"] = "unknown_usage"
                if outcome["status"] == "parsed":
                    outcome["metrics"] = score_page(ParsePage.model_validate(outcome["result"]), references[name])
                (output / f"{filename}.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
                manifest["pages"].append({k: v for k, v in outcome.items() if k != "result"})
                manifest["metric_gate_passed"] = metric_gate(manifest["pages"])
                save()
                print(json.dumps({k: outcome[k] for k in ("document", "page", "profile", "status")}
                                 | {"requests": manifest["requests"], "cost": manifest["estimated_cost_usd"]}), flush=True)
                if manifest["stop_reason"]:
                    return manifest
                if outcome["status"] in ("content_filtered", "refused"):
                    break  # Do not retry a rejected page with a different rendering.
    manifest["stop_reason"] = "completed"
    save()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live is required; no requests were made")
    compare(args.output)


if __name__ == "__main__":
    main()

"""
Eval runner — reads tests/eval/cases.jsonl, runs allocate+pack for each case,
prints per-case results and aggregate metrics.

Usage:
    uv run python tests/eval/run_eval.py
    uv run python tests/eval/run_eval.py --cases path/to/cases.jsonl
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.blocks.models import ContextBlock, ContextRequest
from src.budget.allocator import allocate
from src.budget.policy import load_policy
from src.assembly.packer import pack


# -- case loading --------------------------------------------------------------

def _load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            cases.append(json.loads(line))
    return cases


def _block_from_dict(d: dict) -> ContextBlock:
    return ContextBlock(
        id=d["id"],
        family=d["family"],
        text=d["text"],
        priority=d.get("priority", 50),
        droppable=d.get("droppable", True),
        compressible=d.get("compressible", False),
    )


def _request_from_case(c: dict) -> ContextRequest:
    return ContextRequest(
        blocks=[_block_from_dict(b) for b in c.get("blocks", [])],
        user_message=c["user_message"],
        context_window=c.get("context_window"),
        reserve_output_tokens=c.get("reserve_output_tokens"),
        policy=c.get("policy", "balanced"),
    )


# -- per-case metrics ----------------------------------------------------------

@dataclass
class CaseResult:
    case_id:       str
    passed:        bool
    overflow:      bool        # total_tokens > context_window
    user_present:  bool
    drop_count:    int
    compress_jobs: int
    total_blocks:  int
    leftover:      int
    failures:      list[str]


def _run_case(c: dict) -> CaseResult:
    failures: list[str] = []
    req    = _request_from_case(c)
    policy = load_policy(req.policy)
    plan   = allocate(req, policy)
    result = pack(req, plan, policy)
    r      = result.report

    overflow     = r.token_total > r.context_window
    user_present = any(m["role"] == "user" for m in result.messages)

    expect = c.get("expect", {})

    if expect.get("no_overflow", True) and overflow:
        failures.append(f"OVERFLOW: total={r.token_total} > window={r.context_window}")

    if expect.get("user_present", True) and not user_present:
        failures.append("USER_ABSENT: user message missing from messages")

    max_drops = expect.get("max_drops")
    if max_drops is not None and len(r.dropped) > max_drops:
        failures.append(f"TOO_MANY_DROPS: {len(r.dropped)} > {max_drops}")

    if expect.get("has_compress_jobs") and not plan.compress_jobs and not r.compress_ids:
        failures.append("NO_COMPRESS_JOB: expected at least one compress job")

    return CaseResult(
        case_id=c["id"],
        passed=len(failures) == 0,
        overflow=overflow,
        user_present=user_present,
        drop_count=len(r.dropped),
        compress_jobs=len(r.compress_ids) + len(plan.compress_jobs),
        total_blocks=len(c.get("blocks", [])),
        leftover=r.leftover,
        failures=failures,
    )


# -- aggregate metrics ---------------------------------------------------------

def _aggregate(results: list[CaseResult]) -> dict:
    total_blocks   = sum(r.total_blocks    for r in results)
    total_dropped  = sum(r.drop_count      for r in results)
    total_compress = sum(r.compress_jobs   for r in results)
    return {
        "cases":             len(results),
        "passed":            sum(1 for r in results if r.passed),
        "failed":            sum(1 for r in results if not r.passed),
        "overflow_count":    sum(1 for r in results if r.overflow),   # must be 0
        "drop_rate":         round(total_dropped  / total_blocks, 3) if total_blocks else 0.0,
        "compress_rate":     round(total_compress / total_blocks, 3) if total_blocks else 0.0,
        "avg_leftover":      round(sum(r.leftover for r in results) / len(results), 1),
    }


# -- main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).parent / "cases.jsonl"),
        help="Path to .jsonl eval cases file",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    cases   = _load_cases(Path(args.cases))
    results = [_run_case(c) for c in cases]
    agg     = _aggregate(results)

    if args.json:
        print(json.dumps({"summary": agg, "cases": [
            {"id": r.case_id, "passed": r.passed, "failures": r.failures,
             "drop_count": r.drop_count, "compress_jobs": r.compress_jobs,
             "leftover": r.leftover}
            for r in results
        ]}, indent=2))
        return 0 if agg["overflow_count"] == 0 and agg["failed"] == 0 else 1

    # human-readable
    col = lambda s, w: s.ljust(w)[:w]
    print(f"\n{'-'*72}")
    print(f"  {'ID':<22} {'PASS':>5} {'DROPS':>6} {'CMPR':>5} {'LFTOVR':>7}")
    print(f"{'-'*72}")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  {col(r.case_id, 22)} {mark:>5} {r.drop_count:>6} {r.compress_jobs:>5} {r.leftover:>7}")
        for f in r.failures:
            print(f"    => {f}")
    print(f"{'-'*72}")
    print(f"  Aggregate:")
    print(f"    cases          : {agg['cases']}")
    print(f"    passed         : {agg['passed']} / {agg['cases']}")
    print(f"    overflow_count : {agg['overflow_count']}  <- must be 0")
    print(f"    drop_rate      : {agg['drop_rate']:.1%}")
    print(f"    compress_rate  : {agg['compress_rate']:.1%}")
    print(f"    avg_leftover   : {agg['avg_leftover']:.0f} tokens")
    print(f"{'-'*72}\n")

    return 0 if agg["overflow_count"] == 0 and agg["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

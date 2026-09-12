"""Eval harness: run a JSONL case file through a Pipeline and report the
metrics docs/EVAL.md specified — valid rate, repair rate, mean attempts,
latency. Used by the UI's Eval tab (src/ui/app.py) and directly testable
without one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.pipeline import Pipeline, PipelineFailure
from schemas import registry


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    schema: str
    category: str
    ok: bool
    attempts: int
    latency_ms: float | None
    error_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvalSummary:
    total: int
    valid_rate: float  # ok=True, attempts == 1
    repair_rate: float  # ok=True, attempts > 1
    failure_rate: float  # ok=False
    mean_attempts: float
    mean_latency_ms: float
    results: list[EvalCaseResult]


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def run_eval(pipeline: Pipeline, cases: list[dict]) -> EvalSummary:
    """Runs every case through the same Pipeline instance (schema differs
    per case; provider/model/settings stay whatever the caller configured
    the pipeline with)."""
    results: list[EvalCaseResult] = []
    for i, case in enumerate(cases):
        schema = registry.get(case["schema"])
        try:
            result = pipeline.run(case["text"], schema)
            ok, attempts, latency_ms = result.ok, result.attempts, result.latency_ms
            error_types = [e.type for e in result.errors]
        except PipelineFailure as exc:
            ok, attempts, latency_ms = False, exc.result.attempts, exc.result.latency_ms
            error_types = [e.type for e in exc.result.errors]
        results.append(
            EvalCaseResult(
                case_id=case.get("id", f"case_{i}"),
                schema=case["schema"],
                category=case.get("category", ""),
                ok=ok,
                attempts=attempts,
                latency_ms=latency_ms,
                error_types=error_types,
            )
        )

    total = len(results)
    valid = sum(1 for r in results if r.ok and r.attempts == 1)
    repaired = sum(1 for r in results if r.ok and r.attempts > 1)
    failed = sum(1 for r in results if not r.ok)
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]

    return EvalSummary(
        total=total,
        valid_rate=valid / total if total else 0.0,
        repair_rate=repaired / total if total else 0.0,
        failure_rate=failed / total if total else 0.0,
        mean_attempts=(sum(r.attempts for r in results) / total) if total else 0.0,
        mean_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        results=results,
    )
